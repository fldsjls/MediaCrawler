[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\install-workbench.ps1 first.' }
$arguments = @((Join-Path $PSScriptRoot 'workbench_tools.py'))
if ($CheckOnly) { $arguments += '--check' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Download tool setup failed with exit code $LASTEXITCODE" }
