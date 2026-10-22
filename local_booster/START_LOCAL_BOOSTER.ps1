param([string]$FactoryUrl="https://blackboxlab-factoryos.onrender.com",[string]$Token="",[int]$Port=10000)
$ErrorActionPreference="Stop"
Write-Host "FactoryOS Local Render Booster" -ForegroundColor Cyan
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "Docker Desktop is required for V1." -ForegroundColor Yellow; exit 2 }
if ([string]::IsNullOrWhiteSpace($Token)) { $Token=Read-Host "Paste Local Booster token from FactoryOS AI Media Finisher" }
if ([string]::IsNullOrWhiteSpace($Token)) { throw "Local Booster token is required" }
$root=Split-Path -Parent $PSScriptRoot
Set-Location $root
$data=Join-Path $root ".factoryos-local-media"
New-Item -ItemType Directory -Force -Path $data | Out-Null
Write-Host "Building local Media Finisher image..." -ForegroundColor Cyan
docker build -f media_finisher_worker/Dockerfile -t factoryos-media-finisher-local . | Out-Host
docker rm -f factoryos-media-finisher-local 2>$null | Out-Null
Write-Host "Starting local worker on port $Port..." -ForegroundColor Cyan
docker run -d --name factoryos-media-finisher-local -p "\${Port}:10000" -v "\${data}:/var/data/media-finisher" -e FINISHER_DATA_DIR=/var/data/media-finisher -e FINISHER_WHISPER_MODEL=small -e FINISHER_WHISPER_DEVICE=cpu -e FINISHER_WHISPER_COMPUTE_TYPE=int8 -e FINISHER_GRAPHICS_ENGINE=remotion -e FINISHER_LOW_MEMORY_MODE=0 factoryos-media-finisher-local | Out-Host
py -m pip install -q -r local_booster/requirements.txt
$env:FACTORYOS_URL=$FactoryUrl
$env:FACTORYOS_LOCAL_BOOSTER_TOKEN=$Token
$env:FACTORYOS_LOCAL_WORKER_URL="http://127.0.0.1:$Port"
Write-Host "Booster ONLINE. Keep this window open while FactoryOS should use this PC." -ForegroundColor Green
py local_booster/booster.py
