# Claude Code worker on Android / Termux

The worker itself already runs in daemon mode. The missing layer after a phone reboot is Android/Termux process startup.

## One-time setup

1. Install **Termux:Boot** from the same source as Termux and open Termux:Boot once.
2. In Termux, enter the FactoryOS repository and make sure `claude --version` works under your Claude Pro login.
3. Export the pairing token shown by FactoryOS and run:

```bash
export FACTORY_CLAUDE_WORKER_TOKEN='...'
export AUTOPILOT_REPO="$PWD"
bash autopilot/install_termux_boot.sh
```

The installer stores the worker token only in `~/.config/factoryos/claude-worker.env` with mode 600, creates `~/.termux/boot/factoryos-claude-worker`, takes a wake lock when available, and starts the worker immediately.

The supervisor restarts `python3 -m autopilot.claude_pro_worker` after crashes or network/process exits. It also unsets `ANTHROPIC_API_KEY` so Claude Code uses the logged-in Pro subscription rather than accidentally billing an API key.

## Status

```bash
tail -f ~/.local/state/factoryos/claude-worker.log
ps -A | grep -E 'claude_pro_worker|autopilot'
```

After a phone reboot, FactoryOS should receive a fresh heartbeat automatically once Termux:Boot runs.
