#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$GameDir="${env:ProgramFiles(x86)}/Steam/steamapps/common/Slay the Spire 2",
    [ValidateRange(1024,65535)][int]$Port=18777,
    [switch]$SkipBuild,
    [switch]$ServerOnly,
    [string]$TestScenario=$env:STS2_HEADLESS_SCENARIO,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$ClientArgs
)
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$game=(Resolve-Path -LiteralPath $GameDir).Path
$managed=Join-Path $game 'data_sts2_windows_x86_64'
$contract=Get-Content -LiteralPath (Join-Path $repo 'contracts/sts2-v0.111.0-windows.json') -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath (Join-Path $managed 'sts2.dll') -Algorithm SHA256).Hash -ne $contract.sha256) { throw 'This host requires the verified Windows v0.111.0 assembly.' }
$python=if (Get-Command python -ErrorAction SilentlyContinue) {'python'} elseif (Get-Command py -ErrorAction SilentlyContinue) {'py'} else {throw 'Python 3 is required for the terminal client and isolated runtime staging.'}
$dotnet=Join-Path $env:LOCALAPPDATA 'SlayTheModel/dotnet/dotnet.exe'
if (-not (Test-Path -LiteralPath $dotnet)) {$dotnet='dotnet'}
if (-not $SkipBuild) {
    & $dotnet build (Join-Path $repo 'tools/Sts2.HeadlessHost') -c ExportRelease "-p:Sts2ManagedDir=$managed"
    if ($LASTEXITCODE -ne 0) {throw 'Headless build failed.'}
    & $python (Join-Path $repo 'scripts/headless-stage.py') --platform windows --game $game
    if ($LASTEXITCODE -ne 0) {throw 'Runtime staging failed.'}
}
$stage=Join-Path $repo 'artifacts/headless'
$saved=@{STS2_GAME_PACK=$env:STS2_GAME_PACK;STS2_HEADLESS_PORT=$env:STS2_HEADLESS_PORT;STS2_HEADLESS_USER_DIR=$env:STS2_HEADLESS_USER_DIR;STS2_HEADLESS_SCENARIO=$env:STS2_HEADLESS_SCENARIO}
$process=$null
try {
    $env:STS2_GAME_PACK=Join-Path $game 'SlayTheSpire2.pck'
    $env:STS2_HEADLESS_PORT="$Port"
    $env:STS2_HEADLESS_SCENARIO=$TestScenario
    $env:STS2_HEADLESS_USER_DIR=Join-Path $env:APPDATA 'SlayTheModelHeadless'
    $arguments=@('--headless','--path',('"'+(Join-Path $stage 'project')+'"'),'--log-file',('"'+(Join-Path $stage 'godot.log')+'"'),'--force-steam=off')
    $process=Start-Process -FilePath (Join-Path $stage 'HeadlessHost.exe') -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $stage 'stdout.log') -RedirectStandardError (Join-Path $stage 'stderr.log') -PassThru
    $process.Handle | Out-Null
    $deadline=[DateTime]::UtcNow.AddSeconds(90)
    while ($true) {
        $health=$null
        try {
            $health=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 1
        } catch {
            if ($process.HasExited -or [DateTime]::UtcNow -ge $deadline) {
                Get-Content -LiteralPath (Join-Path $stage 'stdout.log') -Tail 30
                Get-Content -LiteralPath (Join-Path $stage 'stderr.log') -Tail 40
                throw "Headless startup failed; see $stage logs."
            }
            Start-Sleep -Milliseconds 200
        }
        if ($health) {
            if ($health.pid -ne $process.Id) {throw "Port $Port belongs to another process. Choose an unused -Port."}
            break
        }
    }
    if ($ServerOnly) {
        Write-Host "Headless host PID $($process.Id); API http://127.0.0.1:$Port. Logs: $stage"
        $process.WaitForExit()
        $process.Refresh()
        if ($process.ExitCode -ne 0) {throw 'Headless host failed; inspect artifacts/headless/stderr.log.'}
    } else {
        & $python (Join-Path $repo 'scripts/headless-play.py') --url "http://127.0.0.1:$Port" --new @ClientArgs
        if ($LASTEXITCODE -ne 0) {throw 'The terminal client exited with an error.'}
    }
} finally {
    if ($process -and -not $process.HasExited) {Stop-Process -Id $process.Id}
    $env:STS2_GAME_PACK=$saved.STS2_GAME_PACK
    $env:STS2_HEADLESS_PORT=$saved.STS2_HEADLESS_PORT
    $env:STS2_HEADLESS_USER_DIR=$saved.STS2_HEADLESS_USER_DIR
    $env:STS2_HEADLESS_SCENARIO=$saved.STS2_HEADLESS_SCENARIO
}
