$ErrorActionPreference = "Stop"
if (-not $env:FACTORY_URL) { $env:FACTORY_URL = Read-Host "FactoryOS URL" }
if (-not $env:FACTORY_CLAUDE_RUNNER_TOKEN) { $env:FACTORY_CLAUDE_RUNNER_TOKEN = Read-Host "Claude runner token" }
if (-not $env:FACTORY_REPO) { $env:FACTORY_REPO = Read-Host "Local FactoryOS repo path" }
python "$PSScriptRoot\runner.py" --verify --once
if ($LASTEXITCODE -eq 0) {
  Write-Host "Verification heartbeat sent. Start continuous runner with:"
  Write-Host "python `"$PSScriptRoot\runner.py`""
}
