param(
    [string]$Seeds = '1',
    [int]$Simulations = 100,
    [string]$Output = "$PSScriptRoot\deployment\smoke.json"
)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\deployment\run_agent.py" --seeds $Seeds --simulations $Simulations --output $Output
exit $LASTEXITCODE
