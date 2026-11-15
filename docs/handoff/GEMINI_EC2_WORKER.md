# Gemini worker on EC2 (T-607)

Not to be confused with the older issue→PR loop (`tools/gemini_ec2_loop.sh`, since 2026-11-04): that one makes one
JSON generation per `Owner: Gemini` Issue through the Render key. This worker runs Gemini CLI as a full coding agent
(tests, one commit per task) on ROADMAP tasks marked `Owner: gemini`.

The Gemini worker is the third engineering operator. It runs **beside** the Claude worker on the same EC2,
in its own checkout and on its own branch, and takes only ROADMAP tasks marked `Owner: gemini`.

## Free only: Google login, or a key from a project without billing

- Gemini CLI signs in with the owner's **Google account** ("Login with Google", personal free tier). No API key.
- A Gemini API key (AI Studio) is free only while its Google project has no billing; with billing, calls past the
  free quota are paid. So by default the worker **refuses to start** when `GEMINI_API_KEY`, `GOOGLE_API_KEY`,
  `GOOGLE_GENAI_USE_VERTEXAI` or `GOOGLE_APPLICATION_CREDENTIALS` is set, strips them from every run, and writes
  a per-run settings file that enforces the Google-login auth type (`oauth-personal`).
- When the free quota is used up, the run is reported as `subscription_limit` and the queue waits; it is never
  switched to a key. A key is accepted only in the opt-in free-tier key mode below.

### Alternative chosen by the owner (2026-11-15): free-tier API key

If the Google login keeps falling back to "Enter Gemini API Key", use a key from an AI Studio project **without billing**:

1. AI Studio → Projects → **Create project** (e.g. `factoryos-gemini-worker`), so the worker does not share the 5 RPM free
   quota with MyCast / the issue→PR loop that use the Render key. Do **not** click "Set up billing" on it, ever.
2. API Keys → Create API key in that project. Check that its **Billing Tier** column says **Free tier**.
3. Put it only in `~/.config/factoryos/gemini-worker.env` (never in chat, git or Render):
   ```
   FACTORY_GEMINI_AUTH=api-key-free-tier
   GEMINI_API_KEY=<the key>
   # optional: FACTORY_GEMINI_MODEL=<model id shown by /model>
   ```
Without billing Google cannot charge: past the quota requests get HTTP 429 and the worker waits (`subscription_limit`).
Every other key variable (`GOOGLE_API_KEY`, Vertex, service accounts) is still refused.

For an interactive `gemini` session as ec2-user: `/auth` → Use Gemini API Key → Ctrl+C (clears a bad stored key) → paste the key.

## What the worker can and cannot do

| Can | Cannot |
| --- | --- |
| Claim `Owner: gemini` ROADMAP tasks (server claim, run_id) | Claim Claude/ChatGPT/shared tasks or Relay owner tickets |
| Edit, test, make one local commit per task | `git push/merge/rebase/reset --hard`, `gh`, `curl`, `sudo`, deploy (excluded tools; a push is also detected from git refs and fails the run) |
| Push its own branch `autopilot/gemini-worker` (the runner, not the model) | Push to `main` or `autopilot/aws-worker` |
| Report events on its own tickets, send the Gemini lane heartbeat | Use the Claude worker token, owner questions, MyCast, Telegram bot token |

Its token `FACTORY_GEMINI_WORKER_TOKEN` opens only three server paths: `/api/relay/worker/roadmap-claim`
(lane `gemini`), `/api/relay/worker/event` (Gemini-owned tickets) and `/api/operator-worker/heartbeat` (lane `gemini`).

## Owner setup (once)

1. **Google login** (as `ec2-user`):
   ```bash
   env | grep -i -E 'gemini|google_api'   # must print nothing; remove any such line from ~/.bashrc / ~/.profile
   NO_BROWSER=true gemini                 # choose "Login with Google", open the link on the phone, paste the code
   ls ~/.gemini/oauth_creds.json          # must exist
   ```
   If Gemini CLI shows "Enter Gemini API Key", press Esc and type `/auth` → **Login with Google**.
2. **Token**: generate one value and put it in two places.
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(36))"
   ```
   - Render → FactoryOS service → Environment: `FACTORY_GEMINI_WORKER_TOKEN=<value>` (Render redeploys).
   - EC2: `~/.config/factoryos/gemini-worker.env` (then `chmod 600`):
     ```
     FACTORYOS_URL=https://blackboxlab-factoryos.onrender.com
     FACTORY_GEMINI_WORKER_TOKEN=<value>
     # key mode only (see above): FACTORY_GEMINI_AUTH=api-key-free-tier and GEMINI_API_KEY=<free-tier key>
     ```
3. **Own checkout and branch**:
   ```bash
   git clone https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos ~/factoryos-gemini
   cd ~/factoryos-gemini
   git config user.name "FactoryOS Gemini worker"
   git config user.email "<the same address the Claude worker commits with>"
   git checkout -b autopilot/gemini-worker origin/main
   git push -u origin autopilot/gemini-worker
   ```
4. **Service**:
   ```bash
   sudo cp ~/factoryos-gemini/deploy/gemini-worker/factoryos-gemini-worker.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now factoryos-gemini-worker
   journalctl -u factoryos-gemini-worker -f
   ```
   FactoryOS → Workers shows the 🔵 Gemini lane online within a minute.

## Stop / pause

The FactoryOS Pause button controls the Claude worker only. Stop Gemini with
`sudo systemctl stop factoryos-gemini-worker` (start again with `start`).

## First live check (T-607 DONE)

`T-607-P` in ROADMAP is a harmless `Owner: gemini` probe. After setup the worker should: claim it → Telegram
"взята в работу · gemini" → one commit on `autopilot/gemini-worker` → push. Open a PR from that branch to `main`;
CI and Claude review it. Record the outcome in `.autopilot/answers.md` under T-607.
