#!/usr/bin/env bash
# Install the on-demand Codex relay worker on the EC2 host (run as root, idempotent). PR #314 review, blocker 1.
#   factoryos-relay : runs the worker, holds only FACTORY_CODEX_RELAY_TOKEN (systemd credential), no shell.
#   factoryos-codex : runs Codex CLI with an empty environment; owns only its ChatGPT login in its home.
# Neither account can read /opt/factoryos (checkout + .env); the worker's preflight refuses to claim anything
# until that is proven. No paid API: Codex signs in with the owner's ChatGPT subscription (device login, below).
set -euo pipefail
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
CODEX_VERSION="${CODEX_VERSION:-0.167.2}"
CLI_DIR="${CLI_DIR:-/opt/factoryos-codex-cli}"
APP_DIR="${APP_DIR:-/opt/factoryos-codex-relay}"
CODEX_HOME_DIR="${CODEX_HOME_DIR:-/var/lib/factoryos-codex}"
INSTALL_UNITS="${INSTALL_UNITS:-1}"

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
id factoryos-relay >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin --home-dir /nonexistent --no-create-home factoryos-relay
id factoryos-codex >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin --home-dir "$CODEX_HOME_DIR" --create-home factoryos-codex
install -d -m 0700 -o factoryos-codex -g factoryos-codex "$CODEX_HOME_DIR"

# Codex CLI, pinned, root-owned and read-only for both service accounts.
if [ ! -x "$CLI_DIR/node_modules/.bin/codex" ] || ! "$CLI_DIR/node_modules/.bin/codex" --version | grep -q "$CODEX_VERSION"; then
  install -d -m 0755 "$CLI_DIR"
  npm install --prefix "$CLI_DIR" --no-audit --no-fund "@openai/codex@$CODEX_VERSION"
fi
chmod -R go-w "$CLI_DIR"

# Worker code only: three files, no checkout, no .env.
install -d -m 0755 "$APP_DIR/autopilot"
install -m 0644 "$REPO_DIR/agent_secret_scan.py" "$APP_DIR/"
install -m 0644 "$REPO_DIR/autopilot/agent_relay_client.py" "$REPO_DIR/autopilot/codex_relay_worker.py" "$APP_DIR/autopilot/"
: > "$APP_DIR/autopilot/__init__.py"

# The relay account may start programs only as the (less privileged) Codex account.
cat > /etc/sudoers.d/factoryos-codex-relay <<SUDO
Defaults:factoryos-relay !requiretty, env_reset
factoryos-relay ALL=(factoryos-codex) NOPASSWD: ALL
SUDO
chmod 0440 /etc/sudoers.d/factoryos-codex-relay
visudo -cf /etc/sudoers.d/factoryos-codex-relay >/dev/null

install -d -m 0700 /etc/factoryos-codex-relay
if [ "$INSTALL_UNITS" = 1 ]; then
  install -m 0644 "$REPO_DIR/deploy/codex-relay/factoryos-codex-relay.service" "$REPO_DIR/deploy/codex-relay/factoryos-codex-relay.timer" /etc/systemd/system/
  systemctl daemon-reload
fi

cat <<NEXT
Installed. Remaining owner steps (nothing below is automatic):
 1. Token: put FACTORY_CODEX_RELAY_TOKEN (same value as on Render) into /etc/factoryos-codex-relay/token, mode 0600 root.
 2. Base URL: systemctl edit factoryos-codex-relay.service -> [Service] Environment=FACTORYOS_URL=https://...
 3. ChatGPT login for Codex (device code, subscription, no API key):
      sudo -u factoryos-codex -H env -i HOME=$CODEX_HOME_DIR PATH=/usr/bin:/bin $CLI_DIR/node_modules/.bin/codex login --device-auth
 4. Check isolation: cd /opt/factoryos-codex-relay && sudo -u factoryos-relay python3 -m autopilot.codex_relay_worker --check  -> must print "isolated".
 5. Only after review: systemctl enable --now factoryos-codex-relay.timer
NEXT
