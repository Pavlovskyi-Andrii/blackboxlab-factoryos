# T-740 Ops relay: agents can check and restart the EC2 workers without SSH

Owner request 2026-11-25: «нужно сделать так, чтобы у тебя был доступ к этому инстансу… придумай способ». Twice in
three days the Surfer worker needed a manual restart through EC2 Instance Connect, once in a systemd restart loop
(`start-limit-hit`). Cloud agent sessions have no SSH and no AWS credentials, and the agent proxy cannot sign AWS
SigV4 requests. (The task was briefed as "T-729"; that number is the Coordination guard and T-739 is PR #476, so this
is T-740.)

## Shape: pull-based, allowlisted, no shell

```
Claude session --MCP ops_request--> FactoryOS server (queue, gate, limits, audit) <--claim/result-- EC2 ops agent (root timer)
        <--MCP ops_result---------                                   ----Telegram (restart / install only)--> owner
```

Nothing on EC2 listens: the host pulls `/api/ops/worker/claim` every 30 s with the worker credential it already has
(`FACTORY_CLAUDE_WORKER_TOKEN` in `/etc/factoryos/claude-worker.env`). No new secret, no SSH key, no AWS key, no open
port.

## Server (`ops_relay.py`)

- Feature flag `FACTORY_OPS_RELAY_ENABLED` (off by default; the owner sets `1` in Render). Off → every request refused.
- Op classes, `FACTORY_OPS_RELAY_CLASSES` (default `read,restart`): `read` = status, journal, host;
  `restart` = restart; `install` = sync_checkout, install_surfer_unit (off until the owner adds `install`).
- MCP tools on `/mcp`, **Claude lane token only** (T-624 per-lane token; the shared token, ChatGPT and Gemini are
  refused): `ops_request {op, unit?, minutes?, lines?, reason, idempotency_key}` → request id;
  `ops_result {id}` → status + redacted output.
- Limits (rolling 24 h): 30 requests in total, 6 restarts per unit; at most 5 requests waiting at once.
  The same `idempotency_key` returns the same request (different arguments under one key are refused).
- Lifecycle: `queued` → `claimed` → `done` | `failed`; `queued` for 10 min → `expired` (executor not installed or
  offline); `claimed` for 3 min without a result → `failed` (`executor_lost`). Nothing is retried automatically.
- Audit: every request (who, when, op, arguments, reason, result, output) stays in `DATA_DIR/ops_relay.json`
  (last 500). Owner-only JSON `GET /api/ops/owner`, `GET /api/ops/owner/{id}`; Worker Center → technical details →
  card «Ops relay».
- Telegram (notification only, the existing owner chat): one message when a restart / install is queued and one with
  its result.
- Output is redacted on the host and again on the server (credential patterns, `KEY=value` env lines, Authorization
  headers, every known FactoryOS token value) and capped at 32 KB.

## Op catalog (`ops_catalog.py`, shared by server and executor; nothing else exists)

| op | class | arguments | what runs (argv lists, no shell) |
|---|---|---|---|
| status | read | unit (allowlist) | `systemctl show` (state, NRestarts, result), `is-active`, `is-enabled`, last 20 journal lines |
| journal | read | unit, minutes ≤ 180, lines ≤ 300 | `journalctl -u unit --since -Nmin -n lines` |
| host | read | — | `free -m`, `df -h /`, `uptime`, Chrome process count, checkout HEAD vs `origin/main` |
| restart | restart | unit ∈ {surfer worker, claude worker} | `systemctl reset-failed`, `systemctl restart --no-block`, state after 8 s |
| sync_checkout | install | — | as ec2-user: `git fetch origin`, `git merge --ff-only @{u}` (never force, never push) |
| install_surfer_unit | install | — | `bash deploy/install_surfer_worker.sh` (idempotent) |

Read allowlist: `factoryos-surfer-worker.service`, `factoryos-claude-worker.service`,
`factoryos-runner-supervisor.service`, `factoryos-runner-supervisor.timer`, `factoryos-ops-agent.service`,
`factoryos-ops-agent.timer`. Each op has a 60 s deadline; the executor validates the request again against the same
catalog and refuses anything else without running it.

## Executor (`autopilot/ops_agent.py`)

`factoryos-ops-agent.service` (oneshot, root) + `factoryos-ops-agent.timer` (every 30 s). Up to 3 requests per run.
Installed once by the owner: `sudo bash /opt/factoryos/deploy/install_ops_agent.sh` (`[HUMAN] T-740-H`). Restart-loop
detection in the Surfer worker itself stays with T-728 (PR #477); this task only adds the remote `restart`
(reset-failed + restart clears `start-limit-hit`).
