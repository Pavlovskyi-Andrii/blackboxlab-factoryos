# FactoryOS — rules for coding agents (Jules / Gemini, ChatGPT, others)

Claude has its own file (`CLAUDE.md`). This file is for every other agent that works on this repository.

## Who decides
- The **owner** sets direction and priorities and can give any agent a task directly.
- **Claude** coordinates engineering: reviews every pull request, runs the checks and merges. You never merge.
- Gemini: read `docs/handoff/GEMINI_MANUAL.md` before your first task. ChatGPT: `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`.

## Taking a task
1. Work only on a GitHub Issue addressed to you: first body line `Owner: Gemini` (or `Owner: ChatGPT`). For ROADMAP tasks, `Owner:` must name your lane.
2. Check `ROADMAP.md` for `Depends:` and that nobody else owns the task or touches the same files (open PRs).
3. One task = one branch `<agent>/<short-name>` (e.g. `gemini/connection-check`) = one pull request into `main`.

## Hard rules
- Never push to `main` or `autopilot/aws-worker`; never force-push; never delete branches.
- Do not edit `autopilot/` (the live EC2 worker), `.github/workflows/`, `CLAUDE.md`, `AGENTS.md` or `.python-version` unless the issue explicitly asks.
- Never write secrets, tokens, keys or `.env` values into code, tests, issues, PRs or logs. Use environment variables that already exist in `app.py`.
- No paid APIs, paid plans, new cloud resources, ads, real publishing or messages to real people.
- Do not weaken the human approval gate before publishing, authentication, or tests to get a green run.
- Do not claim work you did not verify: say "not verified" instead.

## Done means
- Tests for the change, passing locally where possible and in CI (`FactoryOS CI` must be green on the PR).
- The PR description lists: what changed, which issue/ROADMAP task, the exact commands you ran and their result, what is not verified.
- Local checks for Python changes:
  ```bash
  python -m py_compile app.py smoke_tests.py
  DATA_DIR=/tmp/factoryos-agent FACTORY_PASSWORD="" FACTORY_LLM_API_KEY="" python smoke_tests.py
  ```
  plus the specific `test_*.py` files listed in `.github/workflows/ci.yml` for the area you touched. Dashboard changes: keep EN/UK/RU strings in parity (`test_locale_parity.py`).
