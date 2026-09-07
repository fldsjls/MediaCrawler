[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\setup\install-workbench.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.build\webui\index.html'))) {
    throw 'Web UI is not built. Run scripts\setup\install-workbench.ps1 first.'
}
Push-Location $projectRoot
try {
    $env:PYTHONIOENCODING = 'utf-8'
    Write-Host 'MediaCrawler: http://127.0.0.1:8080 (Ctrl+C stops owned tasks and browsers)'
    & $python (Join-Path $PSScriptRoot 'start-workbench.py')
    if ($LASTEXITCODE -ne 0) { throw "Server exited with code $LASTEXITCODE" }
} finally { Pop-Location }
