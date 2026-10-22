param([string]$FactoryUrl="https://blackboxlab-factoryos.onrender.com",[string]$Token="",[int]$Port=10000,[switch]$Rebuild)
$ErrorActionPreference="Stop"
Write-Host "FactoryOS Local Render Booster" -ForegroundColor Cyan

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "Docker Desktop is not installed or docker.exe is not in PATH." -ForegroundColor Yellow
  exit 2
}

function Test-DockerEngine {
  try {
    docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
  } catch { return $false }
}

if (-not (Test-DockerEngine)) {
  Write-Host "Docker Desktop engine is not running. Starting Docker Desktop..." -ForegroundColor Yellow
  $candidates=@(
    (Join-Path $Env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
    (Join-Path $Env:LocalAppData "Docker\Docker Desktop.exe")
  )
  $desktop=$candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $desktop) {
    Write-Host "Could not find Docker Desktop.exe. Start Docker Desktop manually, wait until it says Engine running, then run this script again." -ForegroundColor Red
    exit 3
  }
  Start-Process $desktop | Out-Null
  $ready=$false
  for($i=0;$i -lt 60;$i++) {
    Start-Sleep -Seconds 2
    if(Test-DockerEngine) { $ready=$true; break }
    if(($i % 5) -eq 4) { Write-Host "Waiting for Docker engine..." -ForegroundColor DarkGray }
  }
  if(-not $ready) {
    Write-Host "Docker Desktop opened, but the Linux engine did not become ready. Verify Docker Desktop shows Engine running / Linux containers." -ForegroundColor Red
    exit 4
  }
}

Write-Host "Docker engine is ready." -ForegroundColor Green
if ([string]::IsNullOrWhiteSpace($Token)) { $Token=Read-Host "Paste Local Booster token from FactoryOS AI Media Finisher" }
if ([string]::IsNullOrWhiteSpace($Token)) { throw "Local Booster token is required" }

$root=Split-Path -Parent $PSScriptRoot
Set-Location $root
$data=Join-Path $root ".factoryos-local-media"
New-Item -ItemType Directory -Force -Path $data | Out-Null

$imageExists=(docker image inspect factoryos-media-finisher-local:latest --format "{{.Id}}" 2>$null)
if($Rebuild -or [string]::IsNullOrWhiteSpace($imageExists)) {
  Write-Host "Building local Media Finisher image..." -ForegroundColor Cyan
  docker build -f media_finisher_worker/Dockerfile -t factoryos-media-finisher-local .
  if($LASTEXITCODE -ne 0) { throw "Docker image build failed" }
} else {
  Write-Host "Using existing local Media Finisher image. Pass -Rebuild to rebuild it." -ForegroundColor Green
}

$existing=docker ps -a --filter "name=^/factoryos-media-finisher-local$" --format "{{.Names}}" 2>$null
if($existing -eq "factoryos-media-finisher-local") {
  docker rm -f factoryos-media-finisher-local | Out-Null
  if($LASTEXITCODE -ne 0) { throw "Could not remove previous local worker container" }
}

$threads=[Math]::Max(2,[Math]::Min(12,[Environment]::ProcessorCount-2))
Write-Host "Starting local worker on port $Port with $threads CPU threads..." -ForegroundColor Cyan
docker run -d --name factoryos-media-finisher-local -p "${Port}:10000" -v "${data}:/var/data/media-finisher" -e FINISHER_DATA_DIR=/var/data/media-finisher -e FINISHER_WHISPER_MODEL=small -e FINISHER_WHISPER_DEVICE=cpu -e FINISHER_WHISPER_COMPUTE_TYPE=int8 -e FINISHER_CPU_THREADS=$threads -e FINISHER_GRAPHICS_ENGINE=remotion -e FINISHER_LOW_MEMORY_MODE=0 factoryos-media-finisher-local
if($LASTEXITCODE -ne 0) { throw "Local worker container failed to start" }

$clientExisting=docker ps -a --filter "name=^/factoryos-local-booster-client$" --format "{{.Names}}" 2>$null
if($clientExisting -eq "factoryos-local-booster-client") {
  docker rm -f factoryos-local-booster-client | Out-Null
}
$boosterDir=Join-Path $root "local_booster"
Write-Host "Starting booster client in Docker. Host Python is not required." -ForegroundColor Cyan
docker run --rm -it --name factoryos-local-booster-client `
  -v "${boosterDir}:/booster:ro" `
  -e FACTORYOS_URL="$FactoryUrl" `
  -e FACTORYOS_LOCAL_BOOSTER_TOKEN="$Token" `
  -e FACTORYOS_LOCAL_WORKER_URL="http://host.docker.internal:$Port" `
  factoryos-media-finisher-local `
  sh -lc "pip install -q requests && python /booster/booster.py"
