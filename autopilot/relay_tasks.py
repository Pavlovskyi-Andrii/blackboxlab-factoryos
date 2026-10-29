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


def git(repo: pathlib.Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False, timeout=25)
    return p.returncode, p.stdout.strip()


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
        "Сформулируй в конце факт выполненного, проверку и следующие шаги.\n\n"
        f"ЗАДАЧА: {title}\n\n{body}\n"
    )


def summarize_result(output: str, code: int, timed_out: bool) -> str:
    if timed_out:
        return "Claude exceeded the bounded execution time; manual Retry required."
    try:
        obj = json.loads(output or "{}")
        msg = str(obj.get("result") or "")
        if not msg:
            msg = "Claude returned no result"
    except (TypeError, json.JSONDecodeError):
        msg = (output or "").strip()
    # Never publish unbounded raw process output into Telegram/Relay.
    msg = " ".join(msg.split())[:440]
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
    if code or dirty:
        report(ticket_id, "blocked", "Runner checkout has uncommitted changes; do not risk overwriting them")
        return {"status": "blocked", "id": ticket_id}
    code, before = git(repo, "rev-parse", "HEAD")
    if code:
        report(ticket_id, "failed", "Cannot read repository HEAD")
        return {"status": "failed", "id": ticket_id}

    prompt = build_prompt(ticket, branch)
    turns = max(4, min(50, int(os.environ.get("RELAY_CLAUDE_MAX_TURNS", "25"))))
    timeout = max(60, min(1800, int(os.environ.get("RELAY_CLAUDE_TIMEOUT_SECONDS", "900"))))
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
            output = str(result.stdout or "")[-8000:]
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
        execute(ticket, repo, status_fn=status_fn)
    except Exception as exc:
        # Avoid printing confidential payloads or raw tracebacks in logs.
        try:
            emit(str(ticket.get("id") or ""), "failed",
                 "Worker internal exception: " + type(exc).__name__,
                 run_id=str((ticket.get("execution") or {}).get("run_id") or ""))
        except Exception:
            pass
    return True
