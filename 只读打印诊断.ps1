param([switch]$NoPause)
& (Join-Path $PSScriptRoot 'PrintDiagnostics.ps1') -NoPause:$NoPause
exit $LASTEXITCODE
