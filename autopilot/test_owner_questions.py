"""Owner desk question answering on the worker: read-only CLI, answer/limit/failure paths. No real Claude calls."""
import json
import subprocess

from autopilot import owner_questions as oq

QUESTION = {"question": {"id": "Q-1", "task_id": "T-506", "step_id": "render",
                         "quote": "Add Environment Variable", "question": "Где эта кнопка?"},
            "runbook_text": "T-506 — Привязать Telegram-бота владельца"}
LIMIT = ('{"type":"result","is_error":true,"api_error_status":429,"api_error":"usage_limit_reached",'
         '"result":"You\'ve hit your session limit \\u00b7 resets 6pm (UTC)"}')


def run(cli_stdout, *, claim=QUESTION, raise_claim=False):
    posts, commands = [], []

    def post(path, data):
        posts.append((path, data))
        if path.endswith("/claim"):
            if raise_claim:
                raise RuntimeError("offline")
            return claim
        return {"ok": True}

    def cli(cmd, **kw):
        commands.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0 if '"is_error":false' in cli_stdout else 1, stdout=cli_stdout, stderr="")

    outcome = oq.answer_one("/tmp", post_fn=post, run_cli=cli)
    return outcome, posts, commands


def main():
    # Nothing queued: no Claude run at all.
    outcome, posts, commands = run("", claim={"question": None})
    assert outcome == ("none", "") and not commands and len(posts) == 1
    outcome, posts, commands = run("", raise_claim=True)
    assert outcome == ("none", "") and not commands

    ok = json.dumps({"type": "result", "is_error": False, "result": "1. Render → Environment.\n2. Save."})
    outcome, posts, commands = run(ok)
    assert outcome == ("answered", ""), outcome
    cmd, kw = commands[0]
    allowed = cmd[cmd.index("--allowedTools") + 1:cmd.index("--disallowedTools")]
    blocked = cmd[cmd.index("--disallowedTools") + 1:]
    assert allowed == ["Read", "Grep", "Glob"], allowed
    assert {"Bash", "Edit", "Write", "WebFetch"} <= set(blocked), blocked
    assert kw["timeout"] == oq.TIMEOUT_SECONDS and "--max-turns" in cmd
    assert "ANTHROPIC_API_KEY" not in kw["env"]
    prompt = cmd[cmd.index("-p") + 1]
    assert "Add Environment Variable" in prompt and "Где эта кнопка?" in prompt and "Никогда не проси" in prompt
    assert posts[-1] == ("/api/factory/owner-desk/worker/answer",
                         {"id": "Q-1", "outcome": "answered", "answer": "1. Render → Environment.\n2. Save."})

    outcome, posts, _ = run(LIMIT)
    assert outcome == ("limit", "6pm (UTC)"), outcome
    assert posts[-1][1]["outcome"] == "requeue", posts

    outcome, posts, _ = run('{"type":"result","is_error":true,"result":"boom"}')
    assert outcome == ("failed", "") and posts[-1][1]["outcome"] == "failed"
    assert "boom" not in posts[-1][1]["answer"]  # raw CLI error text never reaches the owner page
    print("Owner question worker tests passed")


if __name__ == "__main__":
    main()
