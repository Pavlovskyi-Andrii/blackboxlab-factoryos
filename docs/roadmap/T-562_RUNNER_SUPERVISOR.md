# T-562 — Runner Supervisor: subscription-only recovery

Owner rule (2026-10-27): **never activate new paid APIs, pay-as-you-go billing, new chargeable cloud resources, paid browser execution or paid publishing integrations** without new explicit owner approval. Existing paid subscriptions may be used within their plan limits. Never assume subscription access implies API billing is included.

## Responsibilities
- Run on the **existing** EC2 `factoryos-worker` using a local systemd timer; no new cloud resources or extra subscriptions.
- Check local Claude CLI login status via `claude auth status`, never infer success from a past login on another machine.
- Check that an internal FactoryOS worker token exists, the repo is on a non-main branch, Claude CLI is installed, and no PAYG API/Bedrock/Vertex/Foundry override is configured.
- Only start a stopped worker if **all gates pass**.
- Stop a running worker if safety gates become invalid.
- Restart after a crash with at least two minutes between supervisor requests and a maximum of three supervisor restart attempts per hour. Also bound systemd's own automatic restarts to three in ten minutes.
- Persist a local **redacted** JSON status at `/var/lib/factoryos/supervisor-status.json`. The file contains no secrets or auth code.
- On revoked/expired Claude OAuth, CAPTCHA, 2FA, missing token or other account challenge: **block and request owner action**. Never fetch an alternative pay-as-you-go API key; never bypass verification.
- Keep Relay as the owner-facing project/worker status layer. Supervisor is the local lifecycle management layer, separate from browser action execution. Browser Action Runner (T-560) remains a sandboxed web UI execution worker and must not be a general-purpose remote root shell.

## Deployment on an already-approved EC2 (no new resources)
```bash
sudo install -d -m 750 /var/lib/factoryos
sudo install -m 644 deploy/systemd/factoryos-runner-supervisor.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/factoryos-runner-supervisor.timer /etc/systemd/system/
sudo install -d -m 755 /etc/systemd/system/factoryos-claude-worker.service.d
sudo install -m 644 deploy/systemd/factoryos-claude-worker-restarts.conf /etc/systemd/system/factoryos-claude-worker.service.d/limits.conf
sudo systemctl daemon-reload
sudo systemctl enable --now factoryos-runner-supervisor.timer
sudo systemctl start factoryos-runner-supervisor.service
sudo cat /var/lib/factoryos/supervisor-status.json
```

Install only after confirming the code in `/opt/factoryos` matches the approved branch/commit. The supervisor does **not** obtain or generate the internal FactoryOS token: its owner-authorized setup is a separate prerequisite.

## Verification
```bash
python3 -m autopilot.test_supervisor
systemctl status factoryos-runner-supervisor.timer --no-pager
sudo cat /var/lib/factoryos/supervisor-status.json
sudo -u ec2-user claude auth status
```

## Failure semantics
- `blocked: subscription_auth_required`: owner must complete fresh Claude subscription OAuth in trusted interactive terminal; OAuth authorization codes are short-lived and must never be saved in ROADMAP, Git or chat.
- `blocked: factoryos_worker_token_missing`: provision the private, non-billable token matching existing FactoryOS runtime through a secret channel.
- `blocked: paid_api_credentials`: manually remove the pay-as-you-go setting; supervisor will not use it.
- `cooldown`: worker may recover automatically when delay expires.
- `needs_owner: restart_budget_exhausted`: inspect logs and explicitly clear failure before resuming. A fresh authentication never automatically overrides the restart budget.
- `running`: systemd process is active, but useful task progress must be verified separately through verified results and heartbeat.

## Limitations / next phase
This milestone provides **local crash recovery** and a truthful local health status. It does not back up/renew subscription OAuth credentials, bypass 2FA, trigger chat-side tools autonomously, or by itself expose the local status over the FactoryOS web UI. UI integration must use an authenticated endpoint with workspace isolation and redaction. Off-host redundancy requires a separately approved deployment plan because a second machine could incur costs.

## Separate EC2 worker binding (T-563)
FactoryOS may accept an additional `FACTORY_CLAUDE_WORKER_TOKEN_EC2` via its existing Render secret environment. This token is independent of the primary `FACTORY_CLAUDE_WORKER_TOKEN` used by other devices, so provisioning EC2 does not rotate/disconnect existing phone workers. On the trusted EC2 store exactly the same value under `FACTORY_CLAUDE_WORKER_TOKEN` in the root-owned `/etc/factoryos/claude-worker.env`. The service sees only the local name. Generate 32+ random bytes; never store the value in Git, docs, console history or owner-facing status payloads. Verify accepted auth with harmless heartbeat only **after** subscription login has succeeded; never claim live execution before both checks pass.
