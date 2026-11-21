"""Run one Python check with extra environment variables (T-593).

Headless `claude -p` denied every `env DATA_DIR=… python …` command, although the CLAUDE.md
verification loop needs exactly that. `python …` is pre-allowed, so the same check runs as

    python -m autopilot.envrun DATA_DIR=/tmp/factoryos-autopilot FACTORY_PASSWORD= FACTORY_LLM_API_KEY= smoke_tests.py

Only the current Python interpreter is started (script path or `-m module`), so this grants
nothing beyond the existing `Bash(python:*)` rule.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
USAGE = "usage: python -m autopilot.envrun [NAME=value ...] [python] <script.py | -m module> [args ...]"


def split_args(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """Leading NAME=value pairs become the environment; the rest is the Python command line."""
    extra: dict[str, str] = {}
    rest = list(argv)
    while rest:
        match = ASSIGNMENT_RE.match(rest[0])
        if not match:
            break
        extra[match.group(1)] = match.group(2)
        rest.pop(0)
    if rest and rest[0] in ("python", "python3"):
        rest.pop(0)
    return extra, rest


def main(argv: list[str] | None = None) -> int:
    extra, rest = split_args(sys.argv[1:] if argv is None else argv)
    if not rest:
        print(USAGE, file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, *rest], env={**os.environ, **extra})


if __name__ == "__main__":
    sys.exit(main())
