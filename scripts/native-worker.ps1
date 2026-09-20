#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GameDir,
    [int]$TimeoutSeconds = 120,
    [ValidateSet('verify', 'benchmark')][string]$Mode = 'verify',
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$game = (Resolve-Path -LiteralPath $GameDir).Path
$managed = Join-Path $game 'data_sts2_windows_x86_64'
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
        & $dotnet publish $project -c ExportRelease -r win-x64 --self-contained true "-p:Sts2ManagedDir=$managed" -o $output
        if ($LASTEXITCODE -ne 0) { throw 'Worker build failed.' }
        # MegaDot uses a customized managed/native API; keep its matching GodotSharp.
        Copy-Item -LiteralPath (Join-Path $managed 'GodotSharp.dll') -Destination $output -Force
        Copy-Item -LiteralPath (Join-Path $game 'SlayTheSpire2.exe') -Destination (Join-Path $stage 'NativeWorker.exe') -Force
        Copy-Item -LiteralPath (Join-Path $game 'release_info.json') -Destination $stage -Force
    }
    $savedPack = $env:STS2_GAME_PACK
    $savedMode = $env:STS2_WORKER_MODE
    $savedOutput = $env:STS2_BENCHMARK_OUT
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
    }
} finally { Pop-Location }
