[CmdletBinding()]
param([switch]$SkipBuild, [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\setup\install-workbench.ps1 first.' }
Push-Location $projectRoot
try {
    $env:PYTHONIOENCODING = 'utf-8'
    Invoke-Checked $python @((Join-Path $PSScriptRoot 'check-workbench-python.py'))
    Invoke-Checked $python @('-m', 'compileall', '-q', 'src/mediacrawler', 'scripts/runtime/start-workbench.py')
    & (Join-Path $projectRoot 'scripts/setup/install-workbench-tools.ps1') -CheckOnly
    Push-Location (Join-Path $projectRoot 'src\browser-worker')
    try { Invoke-Checked 'npm.cmd' @('run', 'check') } finally { Pop-Location }
    if (-not $SkipTests) {
        Invoke-Checked $python @('-m', 'pytest', '-q', 'tests')
    }
    if (-not $SkipBuild) {
        Push-Location (Join-Path $projectRoot 'src\webui')
        try { Invoke-Checked 'npm.cmd' @('run', 'build') } finally { Pop-Location }
    }
    if ($SkipTests) { Write-Host 'Dependency/static checks passed; pytest was explicitly skipped.' }
    else { Write-Host 'Workbench automated checks passed. Real platform login/download acceptance is separate.' }
} finally { Pop-Location }
