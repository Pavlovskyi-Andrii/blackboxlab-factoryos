# FactoryOS Sandbox (Issue #437)

An independent **static-only** website archive preview service for all MVP Center projects. No production FactoryOS changes.

## Run

```bash
export SANDBOX_ADMIN_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
python sandbox/server.py
```

## Render free service
- Repository: `Pavlovskyi-Andrii/blackboxlab-factoryos`, branch `chatgpt/factoryos-sandbox-437`
- Runtime: Python, region Frankfurt, plan **free**
- Build: `echo Python-stdlib-only`
- Start: `python sandbox/server.py`
- Environment: `SANDBOX_ADMIN_TOKEN` (>=32-char random secret; configured in Render, never checked in)
- Auto deploy: **off**, production services unchanged.

## API
- `GET /health` — public health and version
- `GET /` — browser upload GUI
- `POST /api/upload` — authenticated raw ZIP bytes (`Authorization: Bearer <token>`, `X-Archive-Name` header)
- `POST /api/import-drive` — authenticated JSON `{"file":"public Drive file ID / URL"}`; requires file to be shared for public access
- `GET /api/sites` — authenticated list with expiring preview links
- `GET /p/<site-id>/index.html?exp=...&sig=...` — signed site preview; static HTML, scripts disabled

## Security and limits
Accepts ZIP only (8 MiB maximum), rejects path traversal, symlinks, excessive decompression and unsupported files. Eight concurrent static previews. No shell, package install, JavaScript execution or deployment actions. Preview cookies are HttpOnly, Secure, path-scoped. Imported sites have restrictive CSP `sandbox`, and are not indexed. No private Google Drive OAuth on the server.

**Ephemeral state:** Render free instance can sleep/restart; uploaded archives and previews will disappear. Files are not persistent and no S3/disk billed resource is provisioned. There is no promise of uptime or unlimited free-tier quota.

## Next phases (not implemented)
Private Drive OAuth through scoped connector/owner approval; isolated build runner for React/Next.js with CPU/network/time limits, durable artifact storage, four live JS previews, and gated promotion to Vercel/Render. These require a separate security/cost review.

Issue: https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/437
