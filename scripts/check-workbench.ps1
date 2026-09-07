[CmdletBinding()]
param([switch]$SkipBuild, [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\install-workbench.ps1 first.' }
Push-Location $projectRoot
try {
    $env:PYTHONIOENCODING = 'utf-8'
    Invoke-Checked $python @((Join-Path $PSScriptRoot 'check-workbench-python.py'))
    Invoke-Checked $python @('-m', 'compileall', '-q', 'api/workbench', 'scripts/start-workbench.py')
    & (Join-Path $PSScriptRoot 'install-workbench-tools.ps1') -CheckOnly
    Push-Location (Join-Path $projectRoot 'workers\browser-capture')
    try { Invoke-Checked 'npm.cmd' @('run', 'check') } finally { Pop-Location }
    if (-not $SkipTests) {
        $testPaths = @('tests/test_api_limits.py', 'tests/test_store_factory.py', 'tests/test_cdp_browser.py')
        $testPaths += @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'tests') -Filter 'test_workbench*.py' | ForEach-Object FullName)
        Invoke-Checked $python (@('-m', 'pytest', '-q') + $testPaths)
    }
    if (-not $SkipBuild) {
        Push-Location (Join-Path $projectRoot 'webui')
        try { Invoke-Checked 'npm.cmd' @('run', 'build') } finally { Pop-Location }
    }
    if ($SkipTests) { Write-Host 'Dependency/static checks passed; pytest was explicitly skipped.' }
    else { Write-Host 'Workbench automated checks passed. Real platform login/download acceptance is separate.' }
} finally { Pop-Location }
