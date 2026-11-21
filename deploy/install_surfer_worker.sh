#!/usr/bin/env bash
# T-714-H: install (or refresh) the FactoryOS Surfer worker on the EC2 host. Idempotent: run it again any time.
#   sudo bash /opt/factoryos/deploy/install_surfer_worker.sh
# It copies the systemd unit from the checkout, reloads systemd, enables and (re)starts the unit, and prints its
# status. It reads no secret and changes no env file: the unit uses the existing /etc/factoryos/claude-worker.env.
set -euo pipefail

REPO="${FACTORYOS_REPO:-/opt/factoryos}"
UNIT="factoryos-surfer-worker.service"
SRC="$REPO/deploy/systemd/$UNIT"
DST="/etc/systemd/system/$UNIT"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo bash $REPO/deploy/install_surfer_worker.sh" >&2
  exit 2
fi
if [ ! -f "$SRC" ]; then
  echo "Missing $SRC: the worker checkout has not picked up T-714 from main yet. Wait a few minutes and retry." >&2
  exit 2
fi
if [ ! -f /etc/factoryos/claude-worker.env ]; then
  echo "Missing /etc/factoryos/claude-worker.env (the Claude worker's env file). Pair the worker first." >&2
  exit 2
fi
if ! runuser -u ec2-user -- /usr/bin/python3 -c "import playwright.sync_api" 2>/dev/null; then
  echo "Note: Playwright is not importable for ec2-user; the Surfer worker will wait and report 'unavailable'." >&2
fi

if [ -f "$DST" ] && cmp -s "$SRC" "$DST"; then
  echo "Unit already up to date: $DST"
else
  install -m 644 "$SRC" "$DST"
  echo "Installed $DST"
fi
systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null
systemctl reset-failed "$UNIT" 2>/dev/null || true
systemctl restart "$UNIT"
sleep 5
systemctl --no-pager --lines=15 status "$UNIT" || true
if systemctl is-active --quiet "$UNIT"; then
  echo "OK: $UNIT is active. Worker Center shows the 'Surfer' lane within a minute."
else
  echo "NOT RUNNING: see 'journalctl -u $UNIT -n 50 --no-pager'" >&2
  exit 1
fi
