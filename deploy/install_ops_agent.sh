#!/usr/bin/env bash
# T-740-H: install (or refresh) the FactoryOS ops agent on the EC2 host. Idempotent: run it again any time.
#   sudo bash /opt/factoryos/deploy/install_ops_agent.sh
# It copies factoryos-ops-agent.service + .timer from the checkout, reloads systemd, enables the timer and runs the
# agent once. It reads no secret and changes no env file: the agent uses the existing /etc/factoryos/claude-worker.env.
# It does nothing until the owner sets FACTORY_OPS_RELAY_ENABLED=1 in Render.
set -euo pipefail

REPO="${FACTORYOS_REPO:-/opt/factoryos}"
SERVICE="factoryos-ops-agent.service"
TIMER="factoryos-ops-agent.timer"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo bash $REPO/deploy/install_ops_agent.sh" >&2
  exit 2
fi
for f in "$SERVICE" "$TIMER"; do
  if [ ! -f "$REPO/deploy/systemd/$f" ]; then
    echo "Missing $REPO/deploy/systemd/$f: the worker checkout has not picked up T-740 from main yet. Wait a few minutes and retry." >&2
    exit 2
  fi
done
if [ ! -f "$REPO/autopilot/ops_agent.py" ] || [ ! -f "$REPO/ops_catalog.py" ]; then
  echo "Missing autopilot/ops_agent.py or ops_catalog.py in $REPO: wait for the checkout to update and retry." >&2
  exit 2
fi
if [ ! -f /etc/factoryos/claude-worker.env ]; then
  echo "Missing /etc/factoryos/claude-worker.env (the Claude worker's env file). Pair the worker first." >&2
  exit 2
fi
(cd "$REPO" && /usr/bin/python3 -c "import autopilot.ops_agent") || { echo "autopilot.ops_agent does not import" >&2; exit 1; }

changed=0
for f in "$SERVICE" "$TIMER"; do
  if [ -f "/etc/systemd/system/$f" ] && cmp -s "$REPO/deploy/systemd/$f" "/etc/systemd/system/$f"; then
    echo "Already up to date: /etc/systemd/system/$f"
  else
    install -m 644 "$REPO/deploy/systemd/$f" "/etc/systemd/system/$f"
    echo "Installed /etc/systemd/system/$f"
    changed=1
  fi
done
systemctl daemon-reload
systemctl enable --now "$TIMER" >/dev/null
systemctl start "$SERVICE" || true
sleep 2
systemctl --no-pager --lines=10 status "$SERVICE" || true
if systemctl is-active --quiet "$TIMER"; then
  echo "OK: $TIMER is active (polls FactoryOS every 30 s). Worker Center → Ops relay shows the agent online within a minute."
else
  echo "NOT RUNNING: see 'journalctl -u $SERVICE -n 50 --no-pager'" >&2
  exit 1
fi
