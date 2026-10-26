#!/data/data/com.termux/files/usr/bin/bash
set -u

REPO="${AUTOPILOT_REPO:-$HOME/factoryos}"
ENV_FILE="${FACTORYOS_WORKER_ENV_FILE:-$HOME/.config/factoryos/claude-worker.env}"
STATE_DIR="${FACTORYOS_WORKER_STATE_DIR:-$HOME/.local/state/factoryos}"
LOG_FILE="$STATE_DIR/claude-worker.log"
LOCK_DIR="$STATE_DIR/claude-worker.lock"
RESTART_DELAY="${FACTORYOS_WORKER_RESTART_DELAY:-15}"

mkdir -p "$STATE_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  printf '%s %s\n' "$(date -Iseconds)" "FactoryOS Claude worker supervisor is already running." >>"$LOG_FILE"
  exit 0
fi
cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

export AUTOPILOT_REPO="${AUTOPILOT_REPO:-$REPO}"
export AUTOPILOT_DAEMON="${AUTOPILOT_DAEMON:-1}"
export PYTHONUNBUFFERED=1

command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock >/dev/null 2>&1 || true

while true; do
  printf '%s %s\n' "$(date -Iseconds)" "starting FactoryOS Claude Code worker" >>"$LOG_FILE"

  if [ ! -d "$AUTOPILOT_REPO/.git" ]; then
    printf '%s repo missing: %s\n' "$(date -Iseconds)" "$AUTOPILOT_REPO" >>"$LOG_FILE"
    sleep "$RESTART_DELAY"
    continue
  fi

  if [ -z "${FACTORY_CLAUDE_WORKER_TOKEN:-}" ]; then
    printf '%s token missing in %s\n' "$(date -Iseconds)" "$ENV_FILE" >>"$LOG_FILE"
    sleep "$RESTART_DELAY"
    continue
  fi

  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    unset ANTHROPIC_API_KEY
  fi

  cd "$AUTOPILOT_REPO" || { sleep "$RESTART_DELAY"; continue; }
  python3 -m autopilot.claude_pro_worker >>"$LOG_FILE" 2>&1
  code=$?
  printf '%s worker exited code=%s; restarting in %ss\n' "$(date -Iseconds)" "$code" "$RESTART_DELAY" >>"$LOG_FILE"
  sleep "$RESTART_DELAY"
done
