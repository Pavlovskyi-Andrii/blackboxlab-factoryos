"""Answer owner questions from the FactoryOS owner desk with the existing Claude subscription.

Runs between tasks inside the autopilot loop (never a second concurrent Claude process).
Read-only: Claude may read the repository to check names and routes, but cannot run commands,
edit files or reach the network. Only the answer text goes back to the server.
"""
from __future__ import annotations

import json
import subprocess
import sys

try:
    from . import relay_tasks
    from .delegation import LIMIT_API_ERRORS, cli_error_fields, delegated_env, limit_reset_hint
except ImportError:
    import relay_tasks
    from delegation import LIMIT_API_ERRORS, cli_error_fields, delegated_env, limit_reset_hint

MAX_TURNS = 8
TIMEOUT_SECONDS = 300
READ_ONLY_TOOLS = ("Read", "Grep", "Glob")
BLOCKED_TOOLS = ("Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task")

PROMPT = """Ты — Claude, технический куратор проекта FactoryOS. Владелец выполняет свою задачу по пошаговой
инструкции ниже и задал вопрос по выделенному фрагменту. Владелец — твои руки: он делает действия
в Render, AWS, Telegram, Metricool, ты говоришь, что именно делать.

Как отвечать:
- По-русски, коротко, пронумерованными шагами: что сделать → что должно получиться → что делать, если не получилось.
- Можно читать файлы репозитория (Read/Grep/Glob), чтобы уточнить точные имена переменных, адреса и надписи интерфейса. Ничего не меняй.
- Никогда не проси прислать секрет (токен, пароль, ключ) в чат, Telegram или на сайт и не повторяй секреты. Секреты вводятся только в Render, AWS или терминал.
- Если шаг требует денег (платный тариф, платный API) или необратимого решения — прямо скажи об этом и предложи бесплатную альтернативу, если она есть.
- Если не уверен, так и скажи, и предложи, как проверить.

Инструкция задачи:
{runbook}

Шаг: {step}
Выделенный фрагмент: «{quote}»
Вопрос владельца: {question}
"""


def build_prompt(question: dict, runbook_text: str) -> str:
    return PROMPT.format(runbook=runbook_text or "(инструкция недоступна)", step=question.get("step_id") or "—",
                         quote=question.get("quote") or "—", question=question.get("question") or "")


def build_command(prompt: str) -> list[str]:
    return ["claude", "-p", prompt, "--output-format", "json", "--max-turns", str(MAX_TURNS),
            "--allowedTools", *READ_ONLY_TOOLS, "--disallowedTools", *BLOCKED_TOOLS]


def _answer_text(stdout: str) -> str:
    try:
        value = json.loads(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return ""
    if not isinstance(value, dict) or value.get("is_error") or value.get("type") != "result":
        return ""
    return str(value.get("result") or "").strip()


def answer_one(repo, *, post_fn=None, run_cli=None) -> tuple[str, str]:
    """Returns (outcome, limit_hint). outcome: none | answered | failed | limit."""
    post = post_fn or relay_tasks.post
    if post_fn is None and not relay_tasks.configured():
        return "none", ""
    try:
        claimed = post("/api/factory/owner-desk/worker/claim", {"worker_id": relay_tasks.worker_id()})
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", "")
        log(f"claim failed: {type(exc).__name__} {status}".strip())
        return "none", ""
    question = claimed.get("question") if isinstance(claimed, dict) else None
    if not question:
        return "none", ""
    qid = str(question.get("id") or "")
    log(f"claimed {qid} ({question.get('task_id')})")
    stdout, stderr, exit_code = "", "", "?"
    try:
        result = (run_cli or subprocess.run)(build_command(build_prompt(question, claimed.get("runbook_text", ""))),
                                             cwd=repo, env=delegated_env(), text=True, capture_output=True,
                                             timeout=TIMEOUT_SECONDS, check=False)
        stdout, stderr, exit_code = str(result.stdout or ""), str(result.stderr or ""), result.returncode
    except subprocess.TimeoutExpired:
        stderr = "timeout"
    except OSError:
        stderr = "claude CLI could not start"
    fields = cli_error_fields(stdout + stderr)
    lower = (stdout + stderr).lower()
    if fields.get("api_error") in LIMIT_API_ERRORS or fields.get("api_error_status") == 429 or "hit your" in lower and "limit" in lower:
        _finish(post, qid, "requeue", "")
        log(f"{qid}: subscription limit, requeued")
        return "limit", limit_reset_hint(str(fields.get("result") or stdout))
    answer = _answer_text(stdout)
    if answer:
        _finish(post, qid, "answered", answer)
        log(f"{qid}: answered ({len(answer)} chars)")
        return "answered", ""
    log(f"{qid}: no answer (exit {exit_code})")
    _finish(post, qid, "failed", "Не получилось подготовить ответ (воркер не смог выполнить запрос). Задайте вопрос ещё раз или напишите мне в чат.")
    return "failed", ""


def log(message: str) -> None:
    """One journal line per question; never the question or answer text."""
    print(f"owner-desk: {message}", file=sys.stderr, flush=True)


def _finish(post, qid: str, outcome: str, answer: str) -> None:
    try:
        post("/api/factory/owner-desk/worker/answer", {"id": qid, "outcome": outcome, "answer": answer})
    except Exception as exc:
        # The lease expires on the server and the question returns to the queue.
        log(f"{qid}: posting {outcome} failed: {type(exc).__name__}")
