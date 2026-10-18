# Blackbox Lab — FactoryOS (Render deployment)

This folder is ready to deploy to Render.

## Recommended production MVP
- Render Web Service: `0.5c-512mb` (512 MB)
- Region: Frankfurt
- Persistent disk: 1 GB at `/var/data`
- FastAPI + Uvicorn
- SQLite on the persistent disk for the MVP
- Private login via `FACTORY_USER` / `FACTORY_PASSWORD`

## Deploy
1. Create a GitHub repository and upload the CONTENTS of this folder to the repository root.
2. In Render choose **New > Blueprint**.
3. Connect the repository.
4. Render detects `render.yaml`.
5. When prompted for `FACTORY_PASSWORD`, create a strong private password.
6. Apply the Blueprint and wait for the deploy.
7. Open the generated `https://...onrender.com` URL.
8. Login with:
   - username: `blackboxlab`
   - password: the value you set in Render.

## Why paid + disk?
The current FactoryOS uses SQLite for jobs/events. Render's normal filesystem is ephemeral, so without a persistent disk the state can disappear after restarts/redeploys. The Blueprint mounts a 1 GB persistent disk at `/var/data`.

## Next architecture upgrade
When we add real long-running AI/video jobs or multiple users:
- migrate SQLite -> Render Postgres
- add a background worker / queue
- move generated media to object storage
- add real provider adapters (LLM, voice, video, Metricool)
