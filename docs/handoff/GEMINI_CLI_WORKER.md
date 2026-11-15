# Gemini CLI worker lane (Issue #119)

Owner approval: 2026-11-15. Jules is region-blocked for the owner, so Google's open-source Gemini CLI
(`@google/gemini-cli`, binary `gemini`) runs headless on the **existing** EC2 worker host, as `ec2-user`, next to the
Claude worker. Target: zero additional spend (the owner's personal "Sign in with Google", no API key, no Vertex AI,
no new AWS/Render resources).

> **Read first — a verified fact that may stop this plan.** The official Gemini CLI README (checked 2026-11-15,
> repository HEAD `4ed06ed0`, committed 2026-11-13) says:
>
> > **No free tier or Google AI plans:** Free individual access and **Google AI Pro / Ultra** (Google One) moved to
> > Antigravity CLI on June 18, 2026.
>
> and positions Gemini CLI for "Gemini Code Assist Standard / Enterprise" licences on Google Cloud "(plus legacy paid
> API / Vertex keys)". Source: https://github.com/google-gemini/gemini-cli/blob/main/README.md
>
> The CLI's own client code still contains the free-tier onboarding path, and eligibility is decided by Google's
> server (`packages/core/src/code_assist/setup.ts`), so the only way to know whether the owner's personal account
> still gets access is the one test request in runbook step 4. **If Google answers "not eligible", the lane stays
> blocked by design.** Do not "fix" it with a Gemini API key, a Vertex project or a Code Assist licence: each of those
> can bill, and the worker refuses to start with them. The alternative Google names (Antigravity CLI, `agy`) is not
> implemented here: its headless mode, auth and terms could not be checked from this session (see "Not verified").

## Architecture

```
systemd: factoryos-gemini-worker.service (User=ec2-user, own unit, own checkout)
  └─ python3 -m autopilot.gemini_worker      zero-spend guard, readiness, operator heartbeat (optional)
       └─ python3 -m autopilot.autopilot     SAME runner as Claude, AUTOPILOT_OPERATOR=gemini
            ├─ ROADMAP: only tasks with `Owner: gemini` (never the shared pool)
            ├─ preflight before every claim (CLI, login, branch, guard)  → not ready = no claim
            ├─ POST /api/relay/worker/roadmap-claim  lane=gemini, worker_id=gemini-<host>  (run_id fencing)
            ├─ Relay events running/committed/pushed/done|blocked|failed + heartbeat every 20 s
            └─ delegation.run_delegation(spec from gemini_executor)
                 gemini --prompt … --output-format json --approval-mode yolo --skip-trust
                        --admin-policy autopilot/gemini_policy.toml
                 bounded by AUTOPILOT_TASK_TIMEOUT_SECONDS; on timeout the whole process group is killed
```

- **Checkout:** `/home/ec2-user/factoryos-gemini`, branch `gemini/aws-worker`. The Claude worker keeps
  `/opt/factoryos` on `autopilot/aws-worker`. The unit makes `/opt/factoryos` and `/etc/factoryos` invisible to the lane;
  the preflight also refuses to run inside the Claude checkout. `gemini/issue-N` branches belong to the older
  `tools/gemini_ec2_loop.sh` (API-key proxy loop) and are not touched.
- **What "done" means** is unchanged from the Claude lane: fresh `.autopilot/status.json`, exactly one commit whose
  subject has the task ID, ROADMAP checkbox closed, branch unchanged, no remote ref changed. Then the runner pushes
  `gemini/aws-worker`. PR / CI / merge stay with Claude (the coordinator); the worker never claims them.
- **Zero-spend guard** (names only, values never read or printed): refuses when `GEMINI_API_KEY`, `GOOGLE_API_KEY`,
  `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_GEMINI_BASE_URL`, `GOOGLE_CLOUD_PROJECT`,
  `GOOGLE_CLOUD_PROJECT_ID`, `GEMINI_CLI_USE_COMPUTE_ADC` or `CLOUD_SHELL` is set, or when a `.env` file exists where
  the CLI auto-loads one (`<checkout>/.env`, `<checkout>/.gemini/.env`, `~/.gemini/.env`). The model process gets an
  environment without FactoryOS, GitHub, AWS, Anthropic or Google credentials, with `NO_BROWSER=true`.
- **Quota / limits:** a rate limit parks the whole lane 30 min, an exhausted daily quota 6 h, a lost login 1 h, an
  ineligible account 6 h; none of these counts as a task failure (persisted in `.autopilot/parking.json`, survives
  restarts). Tunables: `GEMINI_QUOTA_BACKOFF_SECONDS`, `GEMINI_DAILY_QUOTA_BACKOFF_SECONDS`,
  `GEMINI_UNAVAILABLE_BACKOFF_SECONDS`.
- **Push fence:** admin-tier policy denies `git push`, `checkout main`, `reset --hard`, `gh pr merge`, reading `.env` /
  `~/.gemini`; the child's `remote.origin.pushurl` points at a dead path; any remote-ref change fails the run.
- **Redaction:** CLI output kept only as a redacted 4000-char local tail (Google API keys `AIza…`, OAuth `ya29.…`,
  refresh `1//…`, `GOCSPX-…`, GitHub and Anthropic tokens, `*_token=` pairs). Model-written summary/need/checks are
  redacted before they reach Relay or Telegram.
- **Restart safety:** reuses `run.json` (stale detection), `parking.json`, server-side claim fencing (a lost run waits
  for the owner's Retry), `RestartPreventExitStatus=3` (guard refusal does not loop), `StartLimitBurst=3`.

Files: `autopilot/gemini_executor.py`, `autopilot/gemini_worker.py`, `autopilot/gemini_policy.toml`,
`autopilot/run_gemini_worker_forever.sh` (non-systemd fallback), `deploy/gemini-worker/*`,
`autopilot/test_gemini_worker.py` (CI step "Gemini CLI lane (Issue #119) …").

## Verified Gemini CLI facts

Sources read on 2026-11-15: the repository at https://github.com/google-gemini/gemini-cli (HEAD `4ed06ed0`,
2026-11-13) and `npm view @google/gemini-cli` (version `0.68.0`, `engines: { node: '>=20' }`).

| Fact | Source |
| --- | --- |
| Install: `npm install -g @google/gemini-cli`; Node `>=20` | README; npm registry metadata |
| Free individual access moved to Antigravity CLI on 2026-06-18; Gemini CLI is aimed at Code Assist Standard/Enterprise | README "Read before installing" |
| `-p/--prompt` forces non-interactive mode; `--output-format text\|json\|stream-json`; JSON = `response`, `stats`, optional `error` | `docs/cli/cli-reference.md`, `docs/cli/headless.md` |
| `--approval-mode default\|auto_edit\|yolo\|plan` (`--yolo` deprecated); `--skip-trust`; `--policy` / `--admin-policy` files | `docs/cli/cli-reference.md`, `packages/cli/src/config/config.ts` |
| Policy rules `[[rule]] toolName / argsPattern / commandPrefix / decision = "deny"`; admin tier wins over user tier | `docs/reference/policy-engine.md` |
| Exit codes: 0 ok, 1 error/API failure, 41 auth, 42 input, 52 config, 53 turn limit | `docs/cli/headless.md`, `packages/core/src/utils/exitCodes.ts` |
| Headless auth uses the auth type saved in `~/.gemini/settings.json` (`security.auth.selectedType`), personal login = `oauth-personal`; otherwise env vars `GEMINI_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_GENAI_USE_GCA` | `packages/cli/src/validateNonInterActiveAuth.ts`, `packages/core/src/core/contentGenerator.ts` |
| Cached login: `~/.gemini/oauth_creds.json` (unless encrypted keychain storage is enabled) | `packages/core/src/config/storage.ts`, `code_assist/oauth2.ts` |
| Login without a browser: `NO_BROWSER=true` → CLI prints a Google URL, redirect is `https://codeassist.google.com/authcode` (not localhost), you paste the shown code at `Enter the authorization code:`; 5-minute limit; impossible in non-interactive mode | `packages/core/src/code_assist/oauth2.ts` |
| The CLI auto-loads the first `.env` walking up from the workspace, else `~/.gemini/.env` | `docs/get-started/authentication.mdx` |
| Docs table recommends API key or Vertex for headless; personal login works headless only via cached credentials | `docs/get-started/authentication.mdx` |
| Server can refuse the free tier: `INELIGIBLE_ACCOUNT`, `UNSUPPORTED_LOCATION`, `RESTRICTED_NETWORK`, `VALIDATION_REQUIRED`, … | `packages/core/src/code_assist/types.ts`, `setup.ts` |
| Quota errors: `TerminalQuotaError` (daily, "You have exhausted your daily quota on this model."), `RetryableQuotaError` (per-minute) | `packages/core/src/utils/googleQuotaErrors.ts` |
| In-repo `docs/resources/quota-and-pricing.md` still lists "1000 requests/user/day" for "Gemini Code Assist (Individual)" — contradicts the README; treat as possibly stale | same file |

**Not verified:** a real run on the EC2 host; whether Google still grants the personal account any Gemini CLI access
today; the actual free-tier limits now; Antigravity CLI (blog post https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/
and https://antigravity.google/ were unreachable from this session's network); Google's terms for automated use of
a personal login; that the policy regexes match every way a model could phrase a push (the dead push URL and the
remote-ref check are the backstops).

## Инструкция для владельца (по шагам)

Все команды — в окне Session Manager на сервере. Секреты (токены, коды входа) никогда не вставляйте в чат и не
показывайте на скриншотах. Код входа Google вставляется только в окно сервера.

### 1. Открыть сервер
1. AWS Console → регион **Stockholm (eu-north-1)** → **EC2** → **Instances** → выберите инстанс воркера
   (`i-087bd3c1bb5de4ec6`) → кнопка **Connect** → вкладка **Session Manager** → **Connect**.
2. Откроется терминал под пользователем `ssm-user`. Перейдите в пользователя воркера:
   ```bash
   sudo -iu ec2-user
   whoami        # должно быть: ec2-user
   ```

### 2. Проверить, что платных ключей нет
```bash
env | grep -E '^(GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENAI_USE_VERTEXAI|GOOGLE_APPLICATION_CREDENTIALS|GOOGLE_CLOUD_PROJECT)=' | cut -d= -f1
ls -a ~/.gemini 2>/dev/null
```
Первая команда должна ничего не вывести (выводятся только имена, не значения). Если в списке `~/.gemini` есть файл
`.env` — не открывайте его в чате; удалите его или перенесите (`mv ~/.gemini/.env ~/gemini-env.bak`), иначе воркер
откажется работать.

### 3. Node 20 и Gemini CLI (без sudo, Claude-воркер не затрагивается)
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
. ~/.nvm/nvm.sh
nvm install 20
node --version                     # v20.x.x
npm install -g @google/gemini-cli
gemini --version                   # например 0.68.0
command -v gemini                  # запомните путь, понадобится в шаге 6
```
Если `curl` к GitHub не проходит — напишите Claude, не ставьте Node «как получится».

### 4. Один раз войти в Google (вручную, в этом же окне)
```bash
cd ~
NO_BROWSER=true gemini
```
1. Если CLI спросит про доверие к папке — выберите вариант доверять. В меню входа выберите **Sign in with Google**
   (не API key, не Vertex AI).
2. CLI напечатает длинную ссылку `https://accounts.google.com/...`. Скопируйте её и откройте на телефоне или ноутбуке,
   войдите **личным** Google-аккаунтом, разрешите доступ.
3. Google покажет код на странице `codeassist.google.com/authcode`. Скопируйте код и вставьте его в окно сервера после
   `Enter the authorization code:`, нажмите Enter. На всё есть 5 минут.
4. Выйдите: введите `/quit`.

Проверка (ничего секретного не выводится):
```bash
ls -l ~/.gemini/oauth_creds.json
grep -o '"selectedType": *"[^"]*"' ~/.gemini/settings.json      # должно быть "oauth-personal"
cd /tmp && gemini --skip-trust -p "Answer with one word: ok" --output-format json | head -c 400; echo
```
Последняя команда тратит 1 запрос. Результаты:
- в ответе есть `"response"` с `ok` — доступ есть, продолжайте;
- текст с `Ineligible`, `not eligible`, `UNSUPPORTED_LOCATION` или упоминанием **Antigravity** — Google больше не даёт
  этому аккаунту бесплатный доступ к Gemini CLI. **Остановитесь** и сообщите Claude. Не добавляйте API-ключ и проект
  Google Cloud: это может стать платным;
- `exhausted your daily quota` / `429` — лимит; повторите завтра.

### 5. Отдельная копия репозитория для Gemini
```bash
cd ~
gh repo clone Pavlovskyi-Andrii/blackboxlab-factoryos factoryos-gemini
cd ~/factoryos-gemini
git checkout -b gemini/aws-worker origin/main
ls -a | grep -x .env || echo "no .env (правильно)"
```
Не копируйте сюда `.env` из `/opt/factoryos`.

### 6. Файл настроек службы (только root, права 600)
Выйдите из `ec2-user` обратно в `ssm-user` (`exit`) и выполните:
```bash
sudo install -m 600 -o root -g root /home/ec2-user/factoryos-gemini/deploy/gemini-worker/gemini-worker.env.example /etc/factoryos/gemini-worker.env
# токен Relay копируется из файла Claude-воркера, на экран не выводится:
sudo grep '^FACTORY_CLAUDE_WORKER_TOKEN=' /etc/factoryos/claude-worker.env | sudo tee -a /etc/factoryos/gemini-worker.env >/dev/null
# путь к gemini и node (из шага 3):
GBIN=$(sudo -iu ec2-user bash -lc '. ~/.nvm/nvm.sh >/dev/null; command -v gemini')
echo "$GBIN"
echo "FACTORY_GEMINI_BIN=$GBIN" | sudo tee -a /etc/factoryos/gemini-worker.env >/dev/null
echo "PATH=$(dirname "$GBIN"):/usr/local/bin:/usr/bin:/bin" | sudo tee -a /etc/factoryos/gemini-worker.env >/dev/null
sudo grep -c '^FACTORY_CLAUDE_WORKER_TOKEN=' /etc/factoryos/gemini-worker.env    # должно быть 1
```
`FACTORY_OPERATOR_WORKER_TOKEN` — необязательно (без него лента Workers не видит «пульс» Gemini, но задачи и события
Relay работают). Не добавляйте ключи Gemini/Google в этот файл.

### 7. Проверка готовности (без запросов к модели)
```bash
sudo systemd-run --pipe --wait -p User=ec2-user -p EnvironmentFile=/etc/factoryos/gemini-worker.env \
  -p WorkingDirectory=/home/ec2-user/factoryos-gemini -E HOME=/home/ec2-user \
  -E AUTOPILOT_REPO=/home/ec2-user/factoryos-gemini /usr/bin/python3 -m autopilot.gemini_worker --check
```
Ожидается `gemini lane: ready · CLI 0.68.0 · branch gemini/aws-worker`. Иначе в списке будет точная причина
(см. таблицу ниже).

### 8. Установить и запустить службу
```bash
sudo cp /home/ec2-user/factoryos-gemini/deploy/gemini-worker/factoryos-gemini-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factoryos-gemini-worker
systemctl status factoryos-gemini-worker --no-pager
sudo journalctl -u factoryos-gemini-worker -n 50 --no-pager
```
`active (running)` — служба работает. Claude-воркер (`factoryos-claude-worker`) этим не затрагивается.

### 9. Как понять, что Gemini реально работает
- Пока в ROADMAP нет задач с `Owner: gemini`, воркер просто ждёт (это нормально). Задачи для Gemini ставит Claude.
- Когда задача взята, в Telegram придёт `📥 T-… взята в работу · gemini · gemini-ec2`, затем события
  running → committed → pushed → done (или blocked с причиной).
- Результат появляется в ветке `gemini/aws-worker` на GitHub. PR, CI и merge делает Claude.

### Если что-то не так

| Что видно (journal / Telegram / `--check`) | Что сделать |
| --- | --- |
| `GEMINI_API_KEY is set …` или другое имя переменной, служба остановилась (exit 3) | Уберите эту переменную из `/etc/factoryos/gemini-worker.env` и профиля ec2-user, затем `sudo systemctl restart factoryos-gemini-worker` |
| `… .env exists; Gemini CLI would load it` | Перенесите указанный файл (не показывая содержимое), перезапустите службу |
| `FACTORY_CLAUDE_WORKER_TOKEN … is not set` | Повторите команду с `grep … tee -a` из шага 6 |
| `Gemini CLI 'gemini' is not installed or does not start` | Шаг 3, затем проверьте строки `FACTORY_GEMINI_BIN` и `PATH` в env-файле (шаг 6) |
| `auth is 'not set'` / `no cached Google login` / `cached Google login is missing or expired` | Шаг 4 заново (как `ec2-user`), затем `sudo systemctl restart factoryos-gemini-worker` |
| `not eligible` / `Ineligible` / `UNSUPPORTED_LOCATION` / `Antigravity` | Бесплатного доступа нет. Остановите службу `sudo systemctl disable --now factoryos-gemini-worker` и сообщите Claude. Ключи не добавлять |
| `gemini lane parked … daily quota` | Ничего: лимит дня исчерпан, линия сама продолжит через ~6 ч |
| `checkout … expected a gemini/* branch` | `cd ~/factoryos-gemini && git checkout gemini/aws-worker` (как `ec2-user`) |
| `is the Claude worker checkout` | В unit-файле/`AUTOPILOT_REPO` указан `/opt/factoryos`; верните `/home/ec2-user/factoryos-gemini` |
| `… is already running by …` / `previous run lost contact; owner Retry required` | Задачу уже кто-то выполняет или прошлый запуск оборвался — нажмите Retry в FactoryOS Workers |
| `start request repeated too quickly` | `sudo journalctl -u factoryos-gemini-worker -n 100 --no-pager`, исправьте причину, затем `sudo systemctl reset-failed factoryos-gemini-worker && sudo systemctl start factoryos-gemini-worker` |

Остановить линию полностью: `sudo systemctl disable --now factoryos-gemini-worker`. Выйти из Google на сервере:
`sudo -iu ec2-user rm ~/.gemini/oauth_creds.json` (и при желании отозвать доступ в настройках Google-аккаунта →
Безопасность → Сторонние приложения).
