"""Execute owner Relay tickets using the *existing Claude Code subscription* worker.

Runs synchronously inside the existing autopilot loop: never starts a second
competing Claude process. Only the verified backend claim turns "queued" into
"claimed". No PAYG API credentials, deploy credentials or auto-publishing.
"""
from __future__ import annotations

import itertools
import json
import os
import pathlib
import re
import socket
import subprocess
import threading
import time

import requests

try:
    from .delegation import delegated_env, DISALLOWED_TOOLS
except ImportError:
    from delegation import delegated_env, DISALLOWED_TOOLS


def endpoint() -> tuple[str, str]:
    return (os.environ.get("FACTORYOS_URL", "").rstrip("/"),
            os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN", ""))


def configured() -> bool:
    url, token = endpoint()
    return bool(url and token)


def worker_id() -> str:
    raw = os.environ.get("FACTORY_CLAUDE_NODE_ID") or ("claude-" + socket.gethostname())
    return re.sub(r"[^A-Za-z0-9_.:-]", "-", raw)[:80]


def post(path: str, data: dict, *, timeout: int = 12) -> dict:
    url, token = endpoint()
    if not url or not token:
        raise RuntimeError("Relay worker connection missing")
    response = requests.post(url + path,
                             headers={"Authorization": "Bearer " + token},
                             json=data, timeout=timeout)
    response.raise_for_status()
    return response.json()


def claim(*, post_fn=None) -> dict | None:
    if not configured():
        return None
    response = (post_fn or post)("/api/relay/worker/claim", {"worker_id": worker_id()})
    return response.get("ticket")


def emit(ticket_id: str, stage: str, note: str = "", evidence: dict | None = None,
         *, post_fn=None, run_id: str = "", event_id: str = "") -> None:
    payload = {
        "ticket_id": ticket_id,
        "worker_id": worker_id(),
        "stage": stage,
        "note": str(note or "")[:650],
        "evidence": evidence or {},
        "run_id": run_id,
        "event_id": event_id,
    }
    try:
        (post_fn or post)("/api/relay/worker/event", payload)
    except requests.RequestException:
        if not event_id:
            raise
        # The backend dedupes by event_id, so one retry cannot duplicate history.
        (post_fn or post)("/api/relay/worker/event", payload)


def claim_roadmap(task: dict, lane: str, *, post_fn=None) -> tuple[dict | None, str]:
    """T-599-C: ask FactoryOS for an exclusive run of one ROADMAP task. No ticket, no work."""
    if not configured() and post_fn is None:
        return None, "FactoryOS worker connection is not configured"
    payload = {
        "worker_id": worker_id(),
        "lane": lane,
        "task_id": str(task.get("id") or ""),
        "title": str(task.get("title") or "")[:150],
        "owner": str(task.get("owner") or ""),
    }
    try:
        response = (post_fn or post)("/api/relay/worker/roadmap-claim", payload)
    except (requests.RequestException, ValueError) as exc:
        return None, "FactoryOS claim unavailable: " + type(exc).__name__
    ticket = response.get("ticket")
    if not isinstance(ticket, dict) or not (ticket.get("execution") or {}).get("run_id"):
        return None, str(response.get("rejected") or "claim rejected")
    return ticket, ""


class RunReporter:
    """Worker-emitted lifecycle events for one claimed run, with a background heartbeat.

    Events carry run_id + sequential event_id so retries never duplicate history.
    Reporting failures never fake progress: they are swallowed, and the server marks
    the run stale when heartbeats stop.
    """

    def __init__(self, ticket: dict, *, emit_fn=None, interval: float = 20.0):
        self.ticket_id = str(ticket.get("id") or "")
        self.run_id = str((ticket.get("execution") or {}).get("run_id") or "")
        self._emit = emit_fn or emit
        self._seq = itertools.count(1)
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __call__(self, stage: str, note: str = "", evidence: dict | None = None) -> None:
        event_id = f"{self.run_id}:{next(self._seq)}:{stage}" if stage != "heartbeat" else ""
        try:
            self._emit(self.ticket_id, stage, note, evidence, run_id=self.run_id, event_id=event_id)
        except Exception:
            pass

    def __enter__(self) -> "RunReporter":
        def beat():
            while not self._stop.wait(self._interval):
                self("heartbeat")
        self._thread = threading.Thread(target=beat, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def git(repo: pathlib.Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False, timeout=25)
    return p.returncode, p.stdout.strip()


def dirty_summary(porcelain: str, limit: int = 5) -> str:
    """Name the paths that make the checkout dirty (status code + path, never file contents).

    2026-11-06: the lane stayed blocked with no hint which file was in the way, and nobody could see the EC2 checkout.
    """
    items = []
    for line in str(porcelain or "").splitlines():
        line = line.strip()
        if not line:
            continue
        code, _, path = line.partition(" ")
        path = re.sub(r"[^\w./@+-]", "_", path.strip().strip('"'))[:80]
        items.append(f"{code[:2]} {path}".strip())
    more = f" +{len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(items[:limit]) + more


def build_prompt(ticket: dict, branch: str) -> str:
    title = str(ticket.get("title") or "")[:180]
    body = str(ticket.get("body") or "")[:10000]
    task_id = str(ticket.get("id") or "")
    return (
        "Ты выполняешь ОДНУ явно поставленную пользователем задачу FactoryOS Relay. "
        f"ID: {task_id}. Git branch: {branch}.\n"
        "Не начинай другие задачи и не переходи в main/master. "
        "Планируй кратко, работай в текущем рабочем каталоге, проверяй результат. "
        "Для изменения кода: коммит только в текущую ветку с ID задачи в сообщении. "
        "НЕ выполняй git push, merge, deploy или публикацию: runner сделает безопасный push отдельно. "
        "НЕ создавай платные ресурсы, НЕ подключай платные API, НЕ используй новые метерированные вызовы. "
        "Используй текущую подписку Claude Code. Не показывай секреты. "
        "Если для задачи нужны оплата, логин/2FA, публикация, другие необратимые действия или интерактивные разрешения, "
        "верни BLOCKED и чётко укажи действие владельца. Не выдавай имитацию за результат.\n"
        "Итоговый ответ пиши ПО-РУССКИ, до 500 символов, тремя пунктами: "
        "1) что сделано (файлы), 2) как проверено, 3) что дальше. Без английских фраз.\n\n"
        f"ЗАДАЧА: {title}\n\n{body}\n"
    )


def summarize_result(output: str, code: int, timed_out: bool) -> str:
    if timed_out:
        return "Claude exceeded the bounded execution time; manual Retry required."
    obj = None
    for candidate in ((output or "").strip(), ((output or "").strip().splitlines() or [""])[-1]):
        try:
            obj = json.loads(candidate or "{}")
            break
        except (TypeError, json.JSONDecodeError):
            obj = None
    if isinstance(obj, dict):
        # R-0074 (owner 2026-11-14): the CLI stops at --max-turns with subtype error_max_turns / stop_reason tool_use;
        # say so plainly instead of dumping a cut JSON tail into Telegram.
        if obj.get("subtype") == "error_max_turns" or (obj.get("is_error") and obj.get("stop_reason") == "tool_use"):
            return (f"Claude исчерпал лимит ходов ({obj.get('num_turns') or '?'}) и не закончил задачу. "
                    "Задача слишком большая для одного прохода: разбейте её на шаги или нажмите Retry.")
        msg = str(obj.get("result") or "") or "Claude returned no result"
    else:
        msg = (output or "").strip()
    # Never publish unbounded raw process output into Telegram/Relay.
    msg = " ".join(msg.split())[:600]
    msg = re.sub(r"(?:sk-ant-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})",
                 "[REDACTED]", msg)
    return msg or ("Claude failed with exit " + str(code))


def execute(ticket: dict, repo: pathlib.Path, *, run_cli=None, emit_fn=None,
            status_fn=None, push_fn=None) -> dict:
    """One bounded invocation; all stage transitions come from real commands."""
    ticket_id = str(ticket.get("id") or "")
    repo = pathlib.Path(repo)
    run_id = str((ticket.get("execution") or {}).get("run_id") or "")
    sequence = itertools.count(1)

    def report(tid: str, stage: str, note: str = "", evidence: dict | None = None) -> None:
        event_id = f"{run_id}:{next(sequence)}:{stage}" if run_id and stage != "heartbeat" else ""
        (emit_fn or emit)(tid, stage, note, evidence, run_id=run_id, event_id=event_id)

    code, branch = git(repo, "branch", "--show-current")
    if code or not branch or branch in ("main", "master"):
        report(ticket_id, "blocked", "Runner is not on a safe non-main branch")
        return {"status": "blocked", "id": ticket_id}
    code, dirty = git(repo, "status", "--porcelain")
    if code:
        report(ticket_id, "blocked", "Runner cannot read git status; do not risk overwriting the checkout")
        return {"status": "blocked", "id": ticket_id}
    if dirty:
        report(ticket_id, "blocked", "Runner checkout has uncommitted changes (" + dirty_summary(dirty)
               + "); do not risk overwriting them")
        return {"status": "blocked", "id": ticket_id}
    code, before = git(repo, "rev-parse", "HEAD")
    if code:
        report(ticket_id, "failed", "Cannot read repository HEAD")
        return {"status": "failed", "id": ticket_id}

    prompt = build_prompt(ticket, branch)
    turns = max(4, min(150, int(os.environ.get("RELAY_CLAUDE_MAX_TURNS", "60"))))
    timeout = max(60, min(3600, int(os.environ.get("RELAY_CLAUDE_TIMEOUT_SECONDS", "1800"))))
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--max-turns", str(turns),
           "--disallowedTools", *DISALLOWED_TOOLS]
    reporter_stop = threading.Event()

    def heartbeat():
        while not reporter_stop.wait(20):
            try:
                report(ticket_id, "heartbeat")
            except Exception:
                pass

    if status_fn:
        status_fn("in_progress", task=ticket_id, summary="Claude Code выполняет Relay запрос")
    report(ticket_id, "running", "Claude Code CLI запущен; ожидание результата", {"branch": branch})
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    code = -1
    output = ""
    timed_out = False
    try:
        try:
            result = (run_cli or subprocess.run)(cmd, cwd=repo, env=delegated_env(),
                                                  text=True, capture_output=True,
                                                  timeout=timeout, check=False)
            code = int(result.returncode)
            output = str(result.stdout or "")[-400000:]
        except subprocess.TimeoutExpired:
            timed_out = True
        except OSError:
            code = -1
    finally:
        reporter_stop.set()
        heartbeat_thread.join(timeout=2)

    _, after_branch = git(repo, "branch", "--show-current")
    _, after = git(repo, "rev-parse", "HEAD")
    if after_branch != branch:
        report(ticket_id, "failed", "Claude changed the current branch unexpectedly")
        return {"status": "failed", "id": ticket_id}
    summary = summarize_result(output, code, timed_out)
    if timed_out or code != 0:
        report(ticket_id, "blocked" if code in (1, 2) else "failed",
               "Claude Code не завершил задачу: " + summary[:350])
        return {"status": "blocked" if code in (1, 2) else "failed", "id": ticket_id}

    _, dirty = git(repo, "status", "--porcelain")
    if dirty:
        report(ticket_id, "blocked", "Claude оставил незакоммиченные изменения; нужна проверка")
        return {"status": "blocked", "id": ticket_id}
    ev = {"branch": branch}
    if after != before:
        ev["commit"] = after
        report(ticket_id, "committed", "Git commit создан в локальной ветке " + branch, ev)
        rc = (push_fn or (lambda: git(repo, "push", "origin", branch)[0]))()
        if rc != 0:
            report(ticket_id, "blocked", "Commit есть локально, но push не удался; требуется повторная отправка", ev)
            return {"status": "blocked", "id": ticket_id}
        ev["pushed"] = True
        report(ticket_id, "pushed", "Git push завершился успешно; CI/merge отдельно не подтверждены", ev)

    report(ticket_id, "done", "Claude завершил запрос. " + summary, ev)
    if status_fn:
        status_fn("idle", summary="Relay " + ticket_id + ": выполнено")
    return {"status": "done", "id": ticket_id, **ev}


PR_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/\d+")


def relay_branch(ticket_id: str, run_id: str) -> str:
    """relay/r-0123-1a2b3c4d: one branch per ticket run, never main, safe characters only."""
    tid = re.sub(r"[^a-z0-9-]", "", str(ticket_id or "").lower())[:20] or "ticket"
    run = re.sub(r"[^a-z0-9]", "", str(run_id or "").lower())[-8:] or "run"
    return f"relay/{tid}-{run}"


def open_pr(workdir: pathlib.Path, branch: str, ticket: dict, run_id: str) -> tuple[str, str]:
    """`gh pr create` with the worker's existing GitHub login. Returns (url, reason); never merges."""
    tid = str(ticket.get("id") or "")
    title = f"Relay {tid}: " + " ".join(str(ticket.get("title") or "").split())[:80]
    source = ticket.get("source") or {}
    issue = source.get("issue") or source.get("url") or ""
    body = (f"Created by the FactoryOS Relay Claude worker for {tid} (run {run_id}).\n"
            + (f"Source: {issue}\n" if issue else "")
            + "\nReview before merge. The worker never merges or deploys; CI and merge are reported back to the owner's Telegram.")
    try:
        p = subprocess.run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body],
                           cwd=workdir, text=True, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", "gh unavailable: " + type(exc).__name__
    match = PR_URL_RE.search(p.stdout or "") or PR_URL_RE.search(p.stderr or "")  # "already exists" also prints the URL
    if match:
        return match.group(0), ""
    return "", "gh pr create failed (exit " + str(p.returncode) + ")"


def execute_isolated(ticket: dict, repo: pathlib.Path, *, run_cli=None, emit_fn=None, status_fn=None,
                     git_fn=None, pr_fn=None, push_fn=None) -> dict:
    """#289 round trip: the ticket gets its own branch from fresh origin/main in a separate git worktree.

    The runner's own checkout and branch are never touched (no dirty-tree block, no shared branch). A commit is
    pushed and a PR is opened with the worker's GitHub login; the PR URL goes back to Relay as evidence, and the
    server then follows CI and merge from GitHub. Nothing is merged or deployed here.
    """
    import shutil
    import tempfile
    ticket_id = str(ticket.get("id") or "")
    repo = pathlib.Path(repo)
    run_id = str((ticket.get("execution") or {}).get("run_id") or "")
    sequence = itertools.count(1)
    g = git_fn or git

    def report(stage: str, note: str = "", evidence: dict | None = None) -> None:
        event_id = f"{run_id}:{next(sequence)}:{stage}" if run_id and stage != "heartbeat" else ""
        (emit_fn or emit)(ticket_id, stage, note, evidence, run_id=run_id, event_id=event_id)

    branch = relay_branch(ticket_id, run_id)
    if g(repo, "fetch", "origin", "main")[0] != 0:
        report("blocked", "Cannot fetch origin/main; the ticket did not start")
        return {"status": "blocked", "id": ticket_id}
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="relay-" + (ticket_id or "x") + "-"))
    shutil.rmtree(workdir, ignore_errors=True)  # git worktree add creates it
    if g(repo, "worktree", "add", "-b", branch, str(workdir), "origin/main")[0] != 0:
        report("blocked", "Cannot create the isolated worktree for branch " + branch)
        return {"status": "blocked", "id": ticket_id}
    try:
        code, before = g(workdir, "rev-parse", "HEAD")
        if code:
            report("failed", "Cannot read the worktree HEAD")
            return {"status": "failed", "id": ticket_id}
        if status_fn:
            status_fn("in_progress", task=ticket_id, summary="Claude Code выполняет Relay запрос")
        report("running", "Claude Code CLI запущен в отдельной ветке " + branch + " от свежего main", {"branch": branch})
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(20):
                try:
                    report("heartbeat")
                except Exception:
                    pass

        hb = threading.Thread(target=heartbeat, daemon=True)
        hb.start()
        turns = max(4, min(150, int(os.environ.get("RELAY_CLAUDE_MAX_TURNS", "60"))))
        timeout = max(60, min(3600, int(os.environ.get("RELAY_CLAUDE_TIMEOUT_SECONDS", "1800"))))
        cmd = ["claude", "-p", build_prompt(ticket, branch), "--output-format", "json", "--max-turns", str(turns),
               "--disallowedTools", *DISALLOWED_TOOLS]
        code, output, timed_out = -1, "", False
        try:
            try:
                result = (run_cli or subprocess.run)(cmd, cwd=workdir, env=delegated_env(), text=True,
                                                      capture_output=True, timeout=timeout, check=False)
                code, output = int(result.returncode), str(result.stdout or "")[-400000:]
            except subprocess.TimeoutExpired:
                timed_out = True
            except OSError:
                code = -1
        finally:
            stop.set()
            hb.join(timeout=2)
        if g(workdir, "branch", "--show-current")[1] != branch:
            report("failed", "Claude changed the branch of the isolated worktree")
            return {"status": "failed", "id": ticket_id}
        summary = summarize_result(output, code, timed_out)
        if timed_out or code != 0:
            stage = "blocked" if code in (1, 2) else "failed"
            report(stage, "Claude Code не завершил задачу: " + summary[:350])
            return {"status": stage, "id": ticket_id}
        if g(workdir, "status", "--porcelain")[1]:
            report("blocked", "Claude оставил незакоммиченные изменения в ветке " + branch + "; нужна проверка")
            return {"status": "blocked", "id": ticket_id}
        after = g(workdir, "rev-parse", "HEAD")[1]
        ev: dict = {"branch": branch}
        if after == before:
            report("done", "Claude завершил запрос без изменений кода. " + summary, ev)
            return {"status": "done", "id": ticket_id, **ev}
        ev["commit"] = after
        report("committed", "Git commit создан в ветке " + branch, ev)
        rc = push_fn() if push_fn else g(workdir, "push", "-u", "origin", branch)[0]
        if rc != 0:
            report("blocked", "Commit есть, но push ветки " + branch + " не удался; Retry", ev)
            return {"status": "blocked", "id": ticket_id}
        ev["pushed"] = True
        report("pushed", "Ветка " + branch + " отправлена на GitHub", ev)
        url, reason = (pr_fn or open_pr)(workdir, branch, ticket, run_id)
        if not url:
            report("blocked", "Ветка отправлена, но PR не создан (" + reason + "); открой PR вручную из " + branch, ev)
            return {"status": "blocked", "id": ticket_id, **ev}
        ev["pr_url"] = url
        report("done", "PR открыт: " + url + " · CI и merge сервер отследит по GitHub. " + summary[:300], ev)
        if status_fn:
            status_fn("idle", summary="Relay " + ticket_id + ": PR открыт")
        return {"status": "done", "id": ticket_id, **ev}
    finally:
        g(repo, "worktree", "remove", "--force", str(workdir))
        g(repo, "worktree", "prune")


def isolated_mode() -> bool:
    return os.environ.get("RELAY_ISOLATED_WORKTREE", "1").strip() != "0"


def run_one(repo: pathlib.Path, *, status_fn=None) -> bool:
    """Claim and execute at most one job; network failures never mark 'done'."""
    if not configured():
        return False
    try:
        ticket = claim()
    except (requests.RequestException, ValueError):
        return False
    if ticket is None:
        return False
    try:
        (execute_isolated if isolated_mode() else execute)(ticket, repo, status_fn=status_fn)
    except Exception as exc:
        # Avoid printing confidential payloads or raw tracebacks in logs.
        try:
            emit(str(ticket.get("id") or ""), "failed",
                 "Worker internal exception: " + type(exc).__name__,
                 run_id=str((ticket.get("execution") or {}).get("run_id") or ""))
        except Exception:
            pass
    return True
