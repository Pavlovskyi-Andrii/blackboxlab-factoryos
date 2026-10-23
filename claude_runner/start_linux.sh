#!/usr/bin/env bash
set -euo pipefail
: "${FACTORY_URL:?Set FACTORY_URL}"
: "${FACTORY_CLAUDE_RUNNER_TOKEN:?Set FACTORY_CLAUDE_RUNNER_TOKEN}"
: "${FACTORY_REPO:?Set FACTORY_REPO}"
python3 "$(dirname "$0")/runner.py" --verify --once
echo "Verification heartbeat sent. Start continuous runner with:"
echo "python3 $(dirname "$0")/runner.py"
