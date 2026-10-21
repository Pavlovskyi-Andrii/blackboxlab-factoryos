FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg nodejs npm chromium fonts-dejavu-core ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY media_finisher_worker/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY media_finisher_worker/remotion/package.json /app/media_finisher_worker/remotion/package.json
WORKDIR /app/media_finisher_worker/remotion
RUN npm install --omit=dev
WORKDIR /app
COPY media_finisher_worker /app/media_finisher_worker
ENV FINISHER_DATA_DIR=/var/data/media-finisher REMOTION_BROWSER_EXECUTABLE=/usr/bin/chromium
CMD ["sh","-c","uvicorn media_finisher_worker.app:app --host 0.0.0.0 --port \${PORT:-10000}"]
