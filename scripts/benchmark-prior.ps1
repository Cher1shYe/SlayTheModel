#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GameDir,
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Checkpoint,
    [int[]]$Seeds = @(1, 2, 3),
    [int[]]$InitialHp = @(80, 40),
    [int]$BudgetMs = 100,
    [string]$OutputDirectory,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repo ('artifacts/prior-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a new output directory to preserve earlier measurements.' }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
$names = @('STS2_PRIOR_SOURCE','STS2_PRIOR_REPO','STS2_PRIOR_MODEL','STS2_PRIOR_ENCOUNTER','STS2_PRIOR_SEED','STS2_PRIOR_HP','STS2_PRIOR_BUDGET_MS')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
    $env:STS2_PRIOR_SOURCE = (Resolve-Path -LiteralPath $Source).Path
    $env:STS2_PRIOR_MODEL = (Resolve-Path -LiteralPath $Checkpoint).Path
    $env:STS2_PRIOR_REPO = $repo
    $env:STS2_PRIOR_ENCOUNTER = 'BYRDONIS_ELITE'
    $env:STS2_PRIOR_BUDGET_MS = [string]$BudgetMs
    $skip = [bool]$SkipBuild
    foreach ($hp in $InitialHp) {
        foreach ($seed in $Seeds) {
            $env:STS2_PRIOR_SEED = [string]$seed
            $env:STS2_PRIOR_HP = [string]$hp
            & (Join-Path $PSScriptRoot 'native-worker.ps1') -GameDir $GameDir -Mode prior-benchmark -SkipBuild:$skip
            Copy-Item -LiteralPath (Join-Path $repo 'artifacts/native-host/benchmark.json') -Destination (Join-Path $OutputDirectory "seed-$seed-hp-$hp.json")
            $skip = $true
        }
    }
    Write-Output "Prior benchmark results: $OutputDirectory"
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
}
