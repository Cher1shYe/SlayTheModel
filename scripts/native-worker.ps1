#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GameDir,
    [string]$RitsuLibRoot = $env:STS2_RITSULIB_DIR,
    [int]$TimeoutSeconds = 120,
    [ValidateSet('verify', 'verify-choices', 'benchmark', 'solver-mcts-benchmark', 'solver-mcts-export')][string]$Mode = 'verify',
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$combatSolverRoot = [System.IO.Path]::GetFullPath((Join-Path $repo 'combat'))
if (-not (Test-Path -LiteralPath (Join-Path $combatSolverRoot 'CombatSolver.csproj'))) {
    throw "Combat Solver source is required at $combatSolverRoot."
}
$sourceCommitPath = Join-Path $combatSolverRoot '.source-commit'
$combatSolverCommit = if (Test-Path -LiteralPath (Join-Path $combatSolverRoot '.git')) {
    (& git -C $combatSolverRoot rev-parse HEAD).Trim()
} elseif (Test-Path -LiteralPath $sourceCommitPath) {
    (Get-Content -LiteralPath $sourceCommitPath -Raw).Trim()
} else {
    ''
}
if ($combatSolverCommit -ne '8826a333a6d48e05f0e368ee2db5d4a15092382e') {
    throw "Combat Solver must be based on verified commit 8826a333; found $combatSolverCommit."
}
$game = (Resolve-Path -LiteralPath $GameDir).Path
$managed = Join-Path $game 'data_sts2_windows_x86_64'
# Steam normally stores Workshop content beside the library's common/ folder.
# A separate Workshop library can be selected with -RitsuLibRoot or the
# STS2_RITSULIB_DIR environment variable.
if (-not $RitsuLibRoot) {
    $steamApps = Split-Path (Split-Path $game -Parent) -Parent
    $RitsuLibRoot = Join-Path $steamApps 'workshop/content/2868840/3747602295'
}
$RitsuLibRoot = [System.IO.Path]::GetFullPath($RitsuLibRoot)
$ritsuCompat = Join-Path $RitsuLibRoot 'compat/0.111.0'
if (-not (Test-Path -LiteralPath (Join-Path $ritsuCompat 'STS2-RitsuLib.dll'))) {
    throw "RitsuLib v0.111.0 not found at $RitsuLibRoot. Pass -RitsuLibRoot or set STS2_RITSULIB_DIR."
}
$contract = Get-Content -LiteralPath (Join-Path $repo 'contracts/sts2-v0.111.0-windows.json') -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath (Join-Path $managed 'sts2.dll') -Algorithm SHA256).Hash -ne $contract.sha256) {
    throw 'The native worker is pinned to the verified Windows v0.111.0 assembly. Revalidate before using another build.'
}
$stage = Join-Path $repo 'artifacts/native-host'
$project = Join-Path $repo 'tools/Sts2.NativeWorker'
$output = Join-Path $stage 'data_NativeWorker_windows_x86_64'
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $project '.godot') | Out-Null
Set-Content -LiteralPath (Join-Path $project '.godot/global_script_class_cache.cfg') -Value 'list=Array[Dictionary]([])' -Encoding Ascii
$dotnet = Join-Path $env:LOCALAPPDATA 'SlayTheModel/dotnet/dotnet.exe'
if (-not (Test-Path -LiteralPath $dotnet)) { $dotnet = 'dotnet' }
Push-Location $repo
try {
    if (-not $SkipBuild) {
        # Pass all platform paths explicitly. CombatSolver otherwise falls back
        # to its own Steam layout, which may point at another library or disk.
        & $dotnet publish $project -c ExportRelease -r win-x64 --self-contained true `
            "-p:Sts2ManagedDir=$managed" `
            "-p:Sts2DataDir=$managed" `
            "-p:CombatSolverRoot=$combatSolverRoot" `
            "-p:RitsuLibRoot=$RitsuLibRoot" `
            "-p:RitsuWorkshopRoot=$RitsuLibRoot" `
            "-p:RitsuLibDir=$ritsuCompat" `
            '-p:CopyModOnBuild=false' `
            -o $output
        if ($LASTEXITCODE -ne 0) { throw 'Worker build failed.' }
        # MegaDot uses a customized managed/native API; keep its matching GodotSharp.
        Copy-Item -LiteralPath (Join-Path $managed 'GodotSharp.dll') -Destination $output -Force
        Copy-Item -LiteralPath (Join-Path $game 'SlayTheSpire2.exe') -Destination (Join-Path $stage 'NativeWorker.exe') -Force
        Copy-Item -LiteralPath (Join-Path $game 'release_info.json') -Destination $stage -Force
    }
    $savedPack = $env:STS2_GAME_PACK
    $savedMode = $env:STS2_WORKER_MODE
    $savedOutput = $env:STS2_BENCHMARK_OUT
    $savedExportOut = $env:STS2_MCTS_EXPORT_OUT
    $savedExportSeed = $env:STS2_MCTS_EXPORT_SEED
    $savedExportEncounter = $env:STS2_MCTS_EXPORT_ENCOUNTER
    $savedExportBudget = $env:STS2_MCTS_EXPORT_BUDGET_MS
    try {
        $env:STS2_GAME_PACK = Join-Path $game 'SlayTheSpire2.pck'
        $env:STS2_WORKER_MODE = $Mode
        $env:STS2_BENCHMARK_OUT = Join-Path $stage 'benchmark.json'
        $process = Start-Process -FilePath (Join-Path $stage 'NativeWorker.exe') -ArgumentList @('--headless', '--path', ('"' + $project + '"')) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $stage 'stdout.txt') -RedirectStandardError (Join-Path $stage 'stderr.txt') -PassThru
        # Windows PowerShell must open the process handle before the process exits
        # or ExitCode can remain unavailable on the returned Process object.
        $process.Handle | Out-Null
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id
            throw "Worker exceeded $TimeoutSeconds seconds; its isolated process was stopped. See artifacts/native-host logs."
        }
        # Drain redirected streams and refresh the process handle before reading
        # ExitCode; otherwise PowerShell can observe $null just after Godot exits.
        $process.WaitForExit()
        $process.Refresh()
        Get-Content -LiteralPath (Join-Path $stage 'stdout.txt') -Tail 12
        Get-Content -LiteralPath (Join-Path $stage 'stderr.txt') -Tail 20
        if ($process.ExitCode -ne 0) { throw "Worker failed with exit $($process.ExitCode)." }
    } finally {
        $env:STS2_GAME_PACK = $savedPack
        $env:STS2_WORKER_MODE = $savedMode
        $env:STS2_BENCHMARK_OUT = $savedOutput
        $env:STS2_MCTS_EXPORT_OUT = $savedExportOut
        $env:STS2_MCTS_EXPORT_SEED = $savedExportSeed
        $env:STS2_MCTS_EXPORT_ENCOUNTER = $savedExportEncounter
        $env:STS2_MCTS_EXPORT_BUDGET_MS = $savedExportBudget
    }
} finally { Pop-Location }
