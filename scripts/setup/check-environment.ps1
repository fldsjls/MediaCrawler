[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$uv = Get-Command uv -ErrorAction SilentlyContinue
$userUv = Join-Path $env:USERPROFILE '.local/bin/uv.exe'
if (-not $uv -and (Test-Path -LiteralPath $userUv)) { $uv = Get-Command $userUv }
Write-Host ('uv (installation tool): ' + $(if ($uv) { $uv.Source } else { 'not found; setup will install it' }))
Write-Host ('Project Python: ' + $python)
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup/install-workbench.ps1 first.' }
& $python -c "import sys; from mediacrawler.paths import PROJECT_ROOT; from mediacrawler.api.main import app; print('Python:', sys.version.split()[0]); print('Package:', PROJECT_ROOT); print('API:', app.title)"
if ($LASTEXITCODE -ne 0) { throw 'Project package/dependencies missing; run scripts/setup/install-workbench.ps1.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is not available.' }
& node -e "if (Number(process.versions.node.split('.')[0]) < 22) process.exit(1); console.log('Node:', process.versions.node)"
if ($LASTEXITCODE -ne 0) { throw 'Node.js 22 or newer is required.' }
Write-Host 'Daily startup uses the project Python; uv does not need to be on PATH.'
