#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Check', 'Build', 'Install', 'Launch', 'Test')]
    [string]$Action = 'Check',
    [string]$GameDir = $env:STS2_GAME_DIR,
    [string]$ManagedDir = $env:Sts2ManagedDir,
    [string]$DatasetDir,
    [ValidateSet('auto', 'no-sl', 'sl')][string]$InformationMode = 'auto',
    [ValidateSet('human')][string]$Actor = 'human'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path $PSScriptRoot -Parent

function Find-Game {
    $roots = @()
    $steam = Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue
    if ($steam -and $steam.PSObject.Properties['SteamPath'] -and $steam.SteamPath) {
        $roots += $steam.SteamPath
    }
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

function Find-Steam {
    $steam = Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue
    if ($steam) {
        if ($steam.PSObject.Properties['SteamExe'] -and $steam.SteamExe -and (Test-Path -LiteralPath $steam.SteamExe -PathType Leaf)) {
            return $steam.SteamExe
        }
        if ($steam.PSObject.Properties['SteamPath'] -and $steam.SteamPath) {
            $candidate = Join-Path $steam.SteamPath 'steam.exe'
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    if (${env:ProgramFiles(x86)}) {
        $candidate = Join-Path ${env:ProgramFiles(x86)} 'Steam\steam.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Steam client not found.'
}

function Invoke-Dotnet([string[]]$Arguments) {
    & $script:dotnet @Arguments
    if ($LASTEXITCODE -ne 0) { throw "dotnet failed (exit $LASTEXITCODE)." }
}

function Write-CollectorConfig([string]$Destination) {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $settings = @{
        SLAY_THE_MODEL_COLLECTOR_ENABLED = '1'
        SLAY_THE_MODEL_DATASET_DIR = $DatasetDir
        SLAY_THE_MODEL_INFORMATION_MODE = $InformationMode
        SLAY_THE_MODEL_COLLECTOR_ACTOR = $Actor
    }
    $path = Join-Path $Destination 'SlayTheModelDataCollector.runtime.json'
    Set-Content -LiteralPath $path -Value ($settings | ConvertTo-Json) -Encoding UTF8
    Write-Host "Runtime config: $path"
}

Push-Location $repo
try {
    $localSdk = Join-Path $env:LOCALAPPDATA 'SlayTheModel/dotnet/dotnet.exe'
    $script:dotnet = if (Test-Path -LiteralPath $localSdk) { $localSdk } else { 'dotnet' }
    Invoke-Dotnet @('--version')

    if ($Action -eq 'Test') {
        Invoke-Dotnet @(
            'build',
            'smoke/SlayTheModel.Collector.Smoke/SlayTheModel.Collector.Smoke.csproj',
            '-c', 'Release', '-m:1', '-nodeReuse:false', '-p:UseSharedCompilation=false')
        Invoke-Dotnet @('smoke/SlayTheModel.Collector.Smoke/bin/Release/net9.0/SlayTheModel.Collector.Smoke.dll')
        return
    }

    if (-not $GameDir) { $GameDir = Find-Game }
    $GameDir = (Resolve-Path -LiteralPath $GameDir).Path
    if (-not $ManagedDir) { $ManagedDir = Join-Path $GameDir 'data_sts2_windows_x86_64' }
    $ManagedDir = (Resolve-Path -LiteralPath $ManagedDir).Path
    foreach ($name in @('SlayTheSpire2.exe', 'SlayTheSpire2.pck')) {
        if (-not (Test-Path -LiteralPath (Join-Path $GameDir $name) -PathType Leaf)) {
            throw "Missing game file: $name"
        }
    }
    foreach ($name in @('sts2.dll', 'GodotSharp.dll', '0Harmony.dll')) {
        if (-not (Test-Path -LiteralPath (Join-Path $ManagedDir $name) -PathType Leaf)) {
            throw "Missing $name in $ManagedDir"
        }
    }
    if (-not $DatasetDir) { $DatasetDir = Join-Path $repo 'artifacts/human-dataset' }
    $DatasetDir = [IO.Path]::GetFullPath($DatasetDir)
    $destination = Join-Path $GameDir 'mods/SlayTheModelDataCollector'
    Write-Host "Game: $GameDir"
    Write-Host "Managed assemblies: $ManagedDir"
    Write-Host "Dataset: $DatasetDir"

    if ($Action -eq 'Check') { return }

    if ($Action -eq 'Launch') {
        if (Get-Process -Name SlayTheSpire2 -ErrorAction SilentlyContinue) {
            throw 'Exit the running game before launching.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $destination 'SlayTheModelDataCollector.dll'))) {
            throw 'Collector is not installed. Run -Action Install first.'
        }
        New-Item -ItemType Directory -Force -Path $DatasetDir | Out-Null
        Write-CollectorConfig $destination
        $steamExe = Find-Steam
        $settings = @{
            SLAY_THE_MODEL_COLLECTOR_ENABLED = '1'
            SLAY_THE_MODEL_DATASET_DIR = $DatasetDir
            SLAY_THE_MODEL_INFORMATION_MODE = $InformationMode
            SLAY_THE_MODEL_COLLECTOR_ACTOR = $Actor
        }
        $previous = @{}
        try {
            foreach ($key in $settings.Keys) {
                $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
                [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process')
            }
            Start-Process -FilePath $steamExe -ArgumentList @('-applaunch', '2868840') -WorkingDirectory (Split-Path $steamExe -Parent)
            Write-Host "Started collector informationMode=$InformationMode actor=$Actor dataset=$DatasetDir"
        } finally {
            foreach ($key in $previous.Keys) {
                [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
            }
        }
        return
    }

    if ($Action -eq 'Install' -and (Get-Process -Name SlayTheSpire2 -ErrorAction SilentlyContinue)) {
        throw 'Exit the game before installing the collector.'
    }
    Invoke-Dotnet @(
        'build',
        'src/SlayTheModel.Sts2.DataCollector/SlayTheModel.Sts2.DataCollector.csproj',
        '-c', 'Release',
        "-p:Sts2ManagedDir=$ManagedDir")

    if ($Action -eq 'Install') {
        New-Item -ItemType Directory -Force -Path $DatasetDir | Out-Null
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -LiteralPath (Join-Path $repo 'src/SlayTheModel.Sts2.DataCollector/bin/Release/net9.0/SlayTheModelDataCollector.dll') -Destination $destination -Force
        Copy-Item -LiteralPath (Join-Path $repo 'src/SlayTheModel.Sts2.DataCollector/SlayTheModelDataCollector.json') -Destination $destination -Force
        Write-CollectorConfig $destination
        Write-Host "Installed: $destination"
    }
} finally {
    Pop-Location
}
