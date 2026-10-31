#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('shadow', 'auto')][string]$Mode = 'auto',
    [switch]$AllowApproximate = $true,
    [string]$GameDir = 'D:\Steam\steamapps\common\Slay the Spire 2'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path $PSScriptRoot -Parent
$runtimePath = Join-Path $GameDir 'mods/SlayTheModelAdapter/SlayTheModelAdapter.runtime.json'
$dllPath = Join-Path $GameDir 'mods/SlayTheModelAdapter/SlayTheModelAdapter.dll'
$manifestPath = Join-Path $repo 'artifacts/armg-network-combined-auto-20261031/manifest.json'
if (Get-Process -Name SlayTheSpire2 -ErrorAction SilentlyContinue) {
    throw 'Exit the running game before changing the ArmG mode or launching.'
}
foreach ($path in @($runtimePath, $dllPath, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file missing: $path" }
}
$expected = (Get-FileHash -LiteralPath (Join-Path $repo 'artifacts/armg-network-combined-auto-20261031/SlayTheModelAdapter.dll') -Algorithm SHA256).Hash
if ((Get-FileHash -LiteralPath $dllPath -Algorithm SHA256).Hash -ne $expected) {
    throw 'Installed Mod does not match the combined ArmG/network build.'
}
if ($Mode -eq 'auto' -and -not $AllowApproximate) {
    throw 'Auto mode requires -AllowApproximate because current live feature mappings are approximate.'
}
$config = Get-Content -LiteralPath $runtimePath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($name in @('SLAY_THE_MODEL_ARMG_PYTHON', 'SLAY_THE_MODEL_ARMG_SERVER', 'SLAY_THE_MODEL_ARMG_CHECKPOINT', 'SLAY_THE_MODEL_ARMG_STS2_ROOT', 'SLAY_THE_MODEL_ARMG_SIMULATOR')) {
    $property = $config.PSObject.Properties[$name]
    if ($null -eq $property -or -not $property.Value -or -not (Test-Path -LiteralPath $property.Value)) {
        throw "Missing ArmG dependency: $name"
    }
}
$steam = Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction Stop
if (-not $steam.SteamExe -or -not (Test-Path -LiteralPath $steam.SteamExe -PathType Leaf)) {
    throw 'Steam executable not found in the current user configuration.'
}
$config | Add-Member -NotePropertyName 'SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY' -NotePropertyValue 'armg' -Force
$config | Add-Member -NotePropertyName 'SLAY_THE_MODEL_ARMG_MODE' -NotePropertyValue $Mode -Force
$config | Add-Member -NotePropertyName 'SLAY_THE_MODEL_ARMG_ALLOW_APPROXIMATE' -NotePropertyValue $(if ($AllowApproximate) { '1' } else { '0' }) -Force
$temp = "$runtimePath.armg.tmp"
try {
    $json = $config | ConvertTo-Json -Depth 16
    [IO.File]::WriteAllText($temp, $json, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temp -Destination $runtimePath -Force
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
}
Start-Process -FilePath $steam.SteamExe -ArgumentList @('-applaunch', '2868840') -WorkingDirectory (Split-Path $steam.SteamExe -Parent)
Write-Host "Started Slay the Spire 2 with ArmG $Mode mode; existing combat configuration was preserved."
