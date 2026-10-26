#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

REPO="${AUTOPILOT_REPO:-$PWD}"
if [ ! -d "$REPO/.git" ]; then
  echo "Run this installer from the FactoryOS repository or export AUTOPILOT_REPO."
  exit 2
fi

for bin in python3 git claude; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Missing required command: $bin"; exit 3; }
done

FACTORYOS_URL="${FACTORYOS_URL:-https://blackboxlab-factoryos.onrender.com}"
: "${FACTORY_CLAUDE_WORKER_TOKEN:?Export FACTORY_CLAUDE_WORKER_TOKEN before running this installer}"

CONFIG_DIR="$HOME/.config/factoryos"
ENV_FILE="$CONFIG_DIR/claude-worker.env"
BOOT_DIR="$HOME/.termux/boot"
BOOT_FILE="$BOOT_DIR/factoryos-claude-worker"
STATE_DIR="$HOME/.local/state/factoryos"

mkdir -p "$CONFIG_DIR" "$BOOT_DIR" "$STATE_DIR"
umask 077
{
  printf 'export FACTORYOS_URL=%q\n' "$FACTORYOS_URL"
  printf 'export FACTORY_CLAUDE_WORKER_TOKEN=%q\n' "$FACTORY_CLAUDE_WORKER_TOKEN"
  printf 'export AUTOPILOT_REPO=%q\n' "$REPO"
  printf 'export AUTOPILOT_DAEMON=1\n'
  printf 'export AUTOPILOT_IDLE_SECONDS=%q\n' "${AUTOPILOT_IDLE_SECONDS:-60}"
} >"$ENV_FILE"
chmod 600 "$ENV_FILE"

cat >"$BOOT_FILE" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
ENV_FILE="$HOME/.config/factoryos/claude-worker.env"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
exec "$AUTOPILOT_REPO/autopilot/run_claude_worker_forever.sh"
BOOT
chmod 700 "$BOOT_FILE"
chmod 700 "$REPO/autopilot/run_claude_worker_forever.sh"

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock >/dev/null 2>&1 || true
fi

# Start immediately. The lock in the supervisor makes this idempotent.
nohup "$REPO/autopilot/run_claude_worker_forever.sh" >/dev/null 2>&1 &

cat <<EOF
FactoryOS Claude worker boot service installed.
Environment: $ENV_FILE
Boot entry:  $BOOT_FILE
Log:         $STATE_DIR/claude-worker.log

Android requirement: install/open Termux:Boot once so Android launches ~/.termux/boot after reboot.
EOF
