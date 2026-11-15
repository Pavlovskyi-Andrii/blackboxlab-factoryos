#!/usr/bin/env bash
# Gemini CLI lane supervisor without systemd (mirrors run_claude_worker_forever.sh). On EC2 prefer
# deploy/gemini-worker/factoryos-gemini-worker.service. Separate checkout, lock, log and env from the Claude worker.
set -u

REPO="${AUTOPILOT_REPO:-$HOME/factoryos-gemini}"
ENV_FILE="${FACTORYOS_GEMINI_ENV_FILE:-$HOME/.config/factoryos/gemini-worker.env}"
STATE_DIR="${FACTORYOS_WORKER_STATE_DIR:-$HOME/.local/state/factoryos}"
LOG_FILE="$STATE_DIR/gemini-worker.log"
LOCK_DIR="$STATE_DIR/gemini-worker.lock"
RESTART_DELAY="${FACTORYOS_WORKER_RESTART_DELAY:-60}"
REFUSED_DELAY=900

mkdir -p "$STATE_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  printf '%s %s\n' "$(date -Iseconds)" "FactoryOS Gemini worker supervisor is already running." >>"$LOG_FILE"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

export AUTOPILOT_REPO="$REPO"
export AUTOPILOT_OPERATOR=gemini
export AUTOPILOT_DAEMON="${AUTOPILOT_DAEMON:-1}"
export PYTHONUNBUFFERED=1

while true; do
  printf '%s %s\n' "$(date -Iseconds)" "starting FactoryOS Gemini CLI worker" >>"$LOG_FILE"
  if [ ! -d "$AUTOPILOT_REPO/.git" ]; then
    printf '%s repo missing: %s\n' "$(date -Iseconds)" "$AUTOPILOT_REPO" >>"$LOG_FILE"
    sleep "$RESTART_DELAY"
    continue
  fi
  cd "$AUTOPILOT_REPO" || { sleep "$RESTART_DELAY"; continue; }
  # The worker itself refuses (exit 3) when a Gemini/Google API key or Vertex setting is present.
  python3 -m autopilot.gemini_worker >>"$LOG_FILE" 2>&1
  code=$?
  delay="$RESTART_DELAY"
  [ "$code" = 3 ] && delay="$REFUSED_DELAY"
  printf '%s worker exited code=%s; restarting in %ss\n' "$(date -Iseconds)" "$code" "$delay" >>"$LOG_FILE"
  sleep "$delay"
done
