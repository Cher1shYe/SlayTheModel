# Compatibility entry point; the shared batch protocol owns discovery and validation.
& (Join-Path $PSScriptRoot 'run-checkpoint-batch.ps1') @args
exit $LASTEXITCODE
