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


## Gemini Omni video provider

FactoryOS can use Google's current Gemini Omni Flash video API directly, without a separate webhook bridge.

Runtime variables:
- `FACTORY_VIDEO_ADAPTER=gemini-omni`
- `FACTORY_GEMINI_API_KEY` — secret; create it in Google AI Studio / a Google Cloud project with Gemini API billing enabled. Never commit it.
- `FACTORY_GEMINI_VIDEO_MODEL=gemini-omni-1.1-flash`
- `FACTORY_GEMINI_VIDEO_ASPECT_RATIO=9:16`
- `FACTORY_GEMINI_VIDEO_RESOLUTION=720p`

Generation uses the Interactions API with URI delivery. FactoryOS stores the Google file id in `media_jobs`, polls the Files API through the existing Refresh render action, downloads the ready MP4 into the persistent media archive, and then exposes the normal signed FactoryOS media URL. Provider credentials are never returned to the browser.

Google AI consumer subscriptions and Gemini API billing are separate products. A Gemini/Google AI Pro subscription does not by itself make the developer API paid tier available; enable billing on the Google Cloud project used by the API key before a paid video test.
