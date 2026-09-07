[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Push-Location $projectRoot
try {
    & npm.cmd run build:web
    if ($LASTEXITCODE -ne 0) { throw 'Web UI build failed.' }
} finally { Pop-Location }
