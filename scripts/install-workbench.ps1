[CmdletBinding()]
param([switch]$SkipChecks)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22 or 24 LTS from https://nodejs.org/en/download, then reopen PowerShell.'
}
Invoke-Checked 'node' @('-e', 'if (parseInt(process.versions.node) < 22) process.exit(1)')
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    $userUv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Path -LiteralPath $userUv) { $uv = Get-Command $userUv }
}
if (-not $uv) {
    # Fixed official installer; install for this user, without changing system policy.
    $uvInstaller = Join-Path ([IO.Path]::GetTempPath()) ('mc-uv-' + [guid]::NewGuid().ToString('N') + '.ps1')
    Invoke-WebRequest 'https://astral.sh/uv/0.12.10/install.ps1' -OutFile $uvInstaller -UseBasicParsing
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uvInstaller
    if ($LASTEXITCODE -ne 0) { throw 'uv installation failed.' }
    $uv = Get-Command (Join-Path $env:USERPROFILE '.local\bin\uv.exe')
}
$previousBrowserGc = $env:PLAYWRIGHT_SKIP_BROWSER_GC
Push-Location $projectRoot
try {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PLAYWRIGHT_SKIP_BROWSER_GC = '1'
    Invoke-Checked $uv.Source @('sync', '--locked')
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    Invoke-Checked $python @('-m', 'playwright', 'install', 'chromium')
    foreach ($directory in @($projectRoot, (Join-Path $projectRoot 'webui'), (Join-Path $projectRoot 'workers\browser-capture'))) {
        Push-Location $directory
        try { Invoke-Checked 'npm.cmd' @('ci', '--no-audit', '--no-fund') } finally { Pop-Location }
    }
    & (Join-Path $PSScriptRoot 'install-workbench-tools.ps1')
    Push-Location (Join-Path $projectRoot 'workers\browser-capture')
    try { Invoke-Checked 'npm.cmd' @('run', 'check') } finally { Pop-Location }
    Push-Location (Join-Path $projectRoot 'webui')
    try { Invoke-Checked 'npm.cmd' @('run', 'build') } finally { Pop-Location }
    if (-not $SkipChecks) { & (Join-Path $PSScriptRoot 'check-workbench.ps1') -SkipBuild }
    Write-Host 'Installed. Start with: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-workbench.ps1'
} finally {
    Pop-Location
    $env:PLAYWRIGHT_SKIP_BROWSER_GC = $previousBrowserGc
}
