#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Check', 'Build', 'Install', 'Launch', 'Probe', 'Test')]
    [string]$Action = 'Check',
    [string]$GameDir = $env:STS2_GAME_DIR,
    [string]$ManagedDir = $env:Sts2ManagedDir,
    [ValidateSet('play', 'train')][string]$RunMode = 'play',
    [ValidateSet('manual', 'first-legal', 'mcts')][string]$CombatPolicy = 'manual',
    [ValidateSet('manual', 'first-legal')][string]$OutsideCombatPolicy = 'manual',
    [ValidateSet('capture', 'first-legal', 'mcts')][string]$Policy,
    [string]$ExportDir,
    [switch]$CaptureHistory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path $PSScriptRoot -Parent

if ($PSBoundParameters.ContainsKey('Policy')) {
    if ($PSBoundParameters.ContainsKey('CombatPolicy')) {
        throw 'Use either -CombatPolicy or the deprecated -Policy parameter, not both.'
    }
    $CombatPolicy = if ($Policy -eq 'capture') { 'manual' } else { $Policy }
    Write-Warning '-Policy is deprecated; use -CombatPolicy instead.'
}

function Find-Game {
    $roots = @()
    $steam = Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue
    if ($steam) { $roots += $steam.SteamPath }
    if (${env:ProgramFiles(x86)}) { $roots += Join-Path ${env:ProgramFiles(x86)} 'Steam' }
    foreach ($root in @($roots)) {
        $vdf = Join-Path $root 'steamapps/libraryfolders.vdf'
        if (Test-Path -LiteralPath $vdf) {
            foreach ($match in [regex]::Matches((Get-Content -LiteralPath $vdf -Raw), '"path"\s+"([^"]+)"')) {
                $roots += $match.Groups[1].Value.Replace('\\', '\')
            }
        }
    }
    foreach ($root in ($roots | Select-Object -Unique)) {
        $candidate = Join-Path $root 'steamapps/common/Slay the Spire 2'
        if (Test-Path -LiteralPath (Join-Path $candidate 'SlayTheSpire2.exe')) { return $candidate }
    }
    throw 'Game not found. Supply -GameDir with the folder containing SlayTheSpire2.exe.'
}

function Invoke-Dotnet([string[]]$Arguments) {
    & $script:dotnet @Arguments
    if ($LASTEXITCODE -ne 0) { throw "dotnet failed (exit $LASTEXITCODE)." }
}

Push-Location $repo
try {
    if ($Action -ne 'Test') {
        if (-not $GameDir) { $GameDir = Find-Game }
        $GameDir = (Resolve-Path -LiteralPath $GameDir).Path
        $exe = Join-Path $GameDir 'SlayTheSpire2.exe'
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Missing game executable: $exe" }
        if (-not $ManagedDir) { $ManagedDir = Join-Path $GameDir 'data_sts2_windows_x86_64' }
        $ManagedDir = (Resolve-Path -LiteralPath $ManagedDir).Path
        foreach ($name in @('sts2.dll', 'GodotSharp.dll', '0Harmony.dll')) {
            if (-not (Test-Path -LiteralPath (Join-Path $ManagedDir $name) -PathType Leaf)) { throw "Missing $name in $ManagedDir" }
        }
        Write-Host "Game: $GameDir"
        Write-Host "Managed assemblies: $ManagedDir"
    }
    if ($Action -eq 'Launch') {
        if (Get-Process -Name SlayTheSpire2 -ErrorAction SilentlyContinue) { throw 'Exit the running game before launching.' }
        if (-not $ExportDir) { $ExportDir = Join-Path $repo 'artifacts/live-capture' }
        $ExportDir = [IO.Path]::GetFullPath($ExportDir)
        New-Item -ItemType Directory -Force -Path $ExportDir | Out-Null
        $settings = @{
            SLAY_THE_MODEL_EXPORT_DIR = $ExportDir
            SLAY_THE_MODEL_CAPTURE_HISTORY = $(if ($CaptureHistory) { '1' } else { $null })
            SLAY_THE_MODEL_RUN_MODE = $RunMode
            SLAY_THE_MODEL_COMBAT_POLICY = $CombatPolicy
            SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY = $OutsideCombatPolicy
            SLAY_THE_MODEL_LIVE_POLICY = $null
            SLAY_THE_MODEL_WORKER_EXE = (Join-Path $repo 'artifacts/native-host/NativeWorker.exe')
            SLAY_THE_MODEL_WORKER_PROJECT = (Join-Path $repo 'tools/Sts2.NativeWorker')
            STS2_GAME_PACK = (Join-Path $GameDir 'SlayTheSpire2.pck')
            SLAY_THE_MODEL_AUTOSLAY_SEED = $null
            SteamAppId = '2868840'
            SteamGameId = '2868840'
        }
        if ($RunMode -eq 'play' -and $CombatPolicy -eq 'mcts' -and -not (Test-Path -LiteralPath $settings.SLAY_THE_MODEL_WORKER_EXE)) {
            throw 'Build and verify the native worker with scripts/native-worker.ps1 -GameDir <game path> first.'
        }
        $previous = @{}
        try {
            foreach ($key in $settings.Keys) {
                $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
                [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process')
            }
            Start-Process -FilePath $exe -WorkingDirectory $GameDir
            Write-Host "Started runMode=$RunMode; combatPolicy=$CombatPolicy; outsideCombatPolicy=$OutsideCombatPolicy; captures=$ExportDir"
        } finally {
            foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
        }
        return
    }
    $localSdk = Join-Path $env:LOCALAPPDATA 'SlayTheModel/dotnet/dotnet.exe'
    $script:dotnet = if (Test-Path -LiteralPath $localSdk) { $localSdk } else { 'dotnet' }
    Invoke-Dotnet @('--version')
    if ($Action -eq 'Check') { return }
    if ($Action -eq 'Test') {
        foreach ($project in @('SlayTheModel.Search.Smoke', 'SlayTheModel.Protocol.Smoke', 'SlayTheModel.Action.Smoke', 'SlayTheModel.ReplaySearch.Smoke')) {
            Invoke-Dotnet @('run', '--project', "smoke/$project/$project.csproj", '-c', 'Release')
        }
        return
    }
    if ($Action -eq 'Probe') {
        Invoke-Dotnet @('run', '--project', 'tools/Sts2.AbiProbe', '--', '--assembly', (Join-Path $ManagedDir 'sts2.dll'), '--contract', 'contracts/sts2-v0.111.0-windows.json', '--out', 'artifacts/abi/sts2-windows.json')
        return
    }
    if ($Action -eq 'Install' -and (Get-Process -Name SlayTheSpire2 -ErrorAction SilentlyContinue)) { throw 'Exit the game before installing the mod.' }
    Invoke-Dotnet @('build', 'src/SlayTheModel.Sts2.ModAdapter', '-c', 'Release', "-p:Sts2ManagedDir=$ManagedDir")
    if ($Action -eq 'Install') {
        $destination = Join-Path $GameDir 'mods/SlayTheModelAdapter'
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -LiteralPath (Join-Path $repo 'src/SlayTheModel.Sts2.ModAdapter/bin/Release/net9.0/SlayTheModelAdapter.dll') -Destination $destination -Force
        Copy-Item -LiteralPath (Join-Path $repo 'src/SlayTheModel.Sts2.ModAdapter/SlayTheModelAdapter.json') -Destination $destination -Force
        Write-Host "Installed: $destination"
    }
} finally { Pop-Location }
