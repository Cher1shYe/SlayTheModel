#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GameDir,
    [string]$RitsuLibRoot = $env:STS2_RITSULIB_DIR,
    [int]$TimeoutSeconds = 120,
    [ValidateSet('verify', 'verify-choices', 'verify-headbutt', 'verify-cross-root', 'verify-enemy-damage', 'benchmark', 'solver-mcts-benchmark', 'solver-mcts-export', 'solver-mcts-diagnosis', 'az-server-smoke')][string]$Mode = 'verify',
    [ValidateSet('pure-mcts', 'policy-value-tree-v1')][string]$SearchMode,
    [string]$OnnxModel,
    [int]$MaxSimulations = 0,
    [int]$BudgetMilliseconds = 0,
    [string]$StageRoot,
    [switch]$CleanupInstanceOnExit,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
if ($PSBoundParameters.ContainsKey('MaxSimulations') -and $MaxSimulations -lt 1) {
    throw '-MaxSimulations must be positive when supplied.'
}
if ($PSBoundParameters.ContainsKey('BudgetMilliseconds') -and ($BudgetMilliseconds -lt 50 -or $BudgetMilliseconds -gt 10000)) {
    throw '-BudgetMilliseconds must be between 50 and 10000 ms when supplied.'
}
if ($SearchMode -eq 'policy-value-tree-v1' -and [string]::IsNullOrWhiteSpace($OnnxModel)) {
    throw 'policy-value-tree-v1 requires -OnnxModel.'
}
if ($SearchMode -eq 'pure-mcts' -and $PSBoundParameters.ContainsKey('OnnxModel')) {
    throw 'pure-mcts cannot load -OnnxModel.'
}
if ($PSBoundParameters.ContainsKey('OnnxModel') -and -not $PSBoundParameters.ContainsKey('SearchMode')) {
    throw '-OnnxModel requires -SearchMode policy-value-tree-v1.'
}
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
$stage = if ($PSBoundParameters.ContainsKey('StageRoot')) {
    if ([string]::IsNullOrWhiteSpace($StageRoot)) { throw '-StageRoot must be a nonempty directory path.' }
    [System.IO.Path]::GetFullPath($StageRoot)
} else {
    Join-Path $repo ('artifacts/native-host/runs/{0}-{1}' -f
        [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'), [Guid]::NewGuid().ToString('N'))
}
$project = Join-Path $repo 'tools/Sts2.NativeWorker'
$output = Join-Path $stage 'data_NativeWorker_windows_x86_64'
if ($SkipBuild) {
    if (-not $PSBoundParameters.ContainsKey('StageRoot') -or
        -not (Test-Path -LiteralPath (Join-Path $stage 'NativeWorker.exe') -PathType Leaf) -or
        -not (Test-Path -LiteralPath $output -PathType Container)) {
        throw '-SkipBuild requires an explicit existing -StageRoot with a published worker.'
    }
} else {
    if (Test-Path -LiteralPath $stage) { throw "StageRoot already exists: $stage" }
    New-Item -ItemType Directory -Force -Path (Split-Path $stage -Parent) | Out-Null
    New-Item -ItemType Directory -Path $stage | Out-Null
}
if ((Test-Path -LiteralPath (Join-Path $stage 'stdout.txt')) -or
    (Test-Path -LiteralPath (Join-Path $stage 'stderr.txt'))) {
    throw "StageRoot already contains worker logs; refusing to overwrite a previous run: $stage"
}
Write-Output "SLAY_NATIVE_WORKER_STAGE=$stage"
New-Item -ItemType Directory -Force -Path (Join-Path $project '.godot') | Out-Null
Set-Content -LiteralPath (Join-Path $project '.godot/global_script_class_cache.cfg') -Value 'list=Array[Dictionary]([])' -Encoding Ascii
$dotnet = Join-Path $env:LOCALAPPDATA 'SlayTheModel/dotnet/dotnet.exe'
if (-not (Test-Path -LiteralPath $dotnet)) { $dotnet = 'dotnet' }
Push-Location $repo
try {
    if (-not $SkipBuild) {
        $publishWatch = [System.Diagnostics.Stopwatch]::StartNew()
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
        $gameExe = Join-Path $game 'SlayTheSpire2.exe'
        $workerExe = Join-Path $stage 'NativeWorker.exe'
        $gameExeSha256 = (Get-FileHash -LiteralPath $gameExe -Algorithm SHA256).Hash
        $workerExeSha256 = if (Test-Path -LiteralPath $workerExe) {
            (Get-FileHash -LiteralPath $workerExe -Algorithm SHA256).Hash
        } else { $null }
        if ($workerExeSha256 -ne $gameExeSha256) {
            Copy-Item -LiteralPath $gameExe -Destination $workerExe -ErrorAction Stop
        }
        if ((Get-FileHash -LiteralPath $workerExe -Algorithm SHA256).Hash -ne $gameExeSha256) {
            throw 'NativeWorker.exe differs from the verified game executable after publish.'
        }
        Copy-Item -LiteralPath (Join-Path $game 'release_info.json') -Destination $stage -Force
        $publishWatch.Stop()
        Write-Output "SLAY_NATIVE_WORKER_PUBLISH_MS=$($publishWatch.Elapsed.TotalMilliseconds)"
    }
    # An explicitly configured run owns the search contract. Clear inherited
    # model/mode/budget knobs first so a stale parent process cannot turn a
    # pure baseline into a network-guided search (or change its cap).
    $searchEnvironmentNames = @(
        'STS2_ALPHAZERO_ONNX_MODEL', 'STS2_ALPHAZERO_SHADOW',
        'STS2_ALPHAZERO_SEARCH_MODE', 'STS2_ALPHAZERO_MAX_SIMULATIONS',
        'STS2_ALPHAZERO_BUDGET_MS', 'STS2_MCTS_EXPORT_MAX_SIMULATIONS',
        'STS2_MCTS_EXPORT_BUDGET_MS')
    $savedSearchEnvironment = @{}
    foreach ($name in $searchEnvironmentNames) {
        $savedSearchEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    $explicitSearchConfig = ($PSBoundParameters.ContainsKey('SearchMode') -or
        $PSBoundParameters.ContainsKey('OnnxModel') -or
        $PSBoundParameters.ContainsKey('MaxSimulations') -or
        $PSBoundParameters.ContainsKey('BudgetMilliseconds'))
    if ($explicitSearchConfig) {
        foreach ($name in $searchEnvironmentNames) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
        if ($PSBoundParameters.ContainsKey('SearchMode')) {
            $env:STS2_ALPHAZERO_SEARCH_MODE = $SearchMode
        }
        if ($PSBoundParameters.ContainsKey('OnnxModel')) {
            $env:STS2_ALPHAZERO_ONNX_MODEL = (Resolve-Path -LiteralPath $OnnxModel).Path
        }
        if ($PSBoundParameters.ContainsKey('MaxSimulations')) {
            $env:STS2_ALPHAZERO_MAX_SIMULATIONS = [string]$MaxSimulations
            $env:STS2_MCTS_EXPORT_MAX_SIMULATIONS = [string]$MaxSimulations
        }
        if ($PSBoundParameters.ContainsKey('BudgetMilliseconds')) {
            $env:STS2_ALPHAZERO_BUDGET_MS = [string]$BudgetMilliseconds
            $env:STS2_MCTS_EXPORT_BUDGET_MS = [string]$BudgetMilliseconds
        }
    }
    $savedPack = $env:STS2_GAME_PACK
    $savedMode = $env:STS2_WORKER_MODE
    $savedOutput = $env:STS2_BENCHMARK_OUT
    $savedExportOut = $env:STS2_MCTS_EXPORT_OUT
    $savedCrossRootOut = $env:STS2_CROSS_ROOT_DIAG_OUT
    $savedEnemyDamageOut = $env:STS2_ENEMY_DAMAGE_DIAG_OUT
    $savedExportSeed = $env:STS2_MCTS_EXPORT_SEED
    $savedExportEncounter = $env:STS2_MCTS_EXPORT_ENCOUNTER
    try {
        $env:STS2_GAME_PACK = Join-Path $game 'SlayTheSpire2.pck'
        $env:STS2_WORKER_MODE = $Mode
        $env:STS2_BENCHMARK_OUT = Join-Path $stage 'benchmark.json'
        if ($Mode -eq 'verify-cross-root') {
            $env:STS2_CROSS_ROOT_DIAG_OUT = Join-Path $stage 'cross-root-reward.json'
        }
        if ($Mode -eq 'verify-enemy-damage') {
            $env:STS2_ENEMY_DAMAGE_DIAG_OUT = Join-Path $stage 'enemy-damage-ledger.json'
        }
        $processWatch = [System.Diagnostics.Stopwatch]::StartNew()
        $process = Start-Process -FilePath (Join-Path $stage 'NativeWorker.exe') -ArgumentList @('--headless', '--path', ('"' + $project + '"')) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $stage 'stdout.txt') -RedirectStandardError (Join-Path $stage 'stderr.txt') -PassThru
        # Windows PowerShell must open the process handle before the process exits
        # or ExitCode can remain unavailable on the returned Process object.
        $process.Handle | Out-Null
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id
            $process.WaitForExit()
            throw "Worker exceeded $TimeoutSeconds seconds; its isolated process was stopped. See $stage logs."
        }
        # Drain redirected streams and refresh the process handle before reading
        # ExitCode; otherwise PowerShell can observe $null just after Godot exits.
        $process.WaitForExit()
        $process.Refresh()
        $processWatch.Stop()
        Write-Output "SLAY_NATIVE_WORKER_PROCESS_MS=$($processWatch.Elapsed.TotalMilliseconds)"
        Get-Content -LiteralPath (Join-Path $stage 'stdout.txt') -Tail 12
        Get-Content -LiteralPath (Join-Path $stage 'stderr.txt') -Tail 20
        $assemblyPattern = '(?m)^SLAY_WORKER_ASSEMBLY label=(NativeWorker|Search|CombatSolver) path=(.+?) mvid=([A-Fa-f0-9-]{36}) sha256=([A-Fa-f0-9]{64})\r?$'
        $assemblyMatches = [regex]::Matches((Get-Content -LiteralPath (Join-Path $stage 'stdout.txt') -Raw), $assemblyPattern)
        if ($assemblyMatches.Count -ne 3) { throw "Worker assembly provenance is incomplete; see $stage logs." }
        $assemblies = @()
        $seenLabels = @{}
        $outputPrefix = $output.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
        foreach ($match in $assemblyMatches) {
            $label = $match.Groups[1].Value
            $assemblyPath = [System.IO.Path]::GetFullPath($match.Groups[2].Value)
            if ($seenLabels.ContainsKey($label) -or
                -not $assemblyPath.StartsWith($outputPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
                -not (Test-Path -LiteralPath $assemblyPath -PathType Leaf)) {
                throw "Worker loaded $label outside this stage or reported a duplicate identity: $assemblyPath"
            }
            $seenLabels[$label] = $true
            $diskHash = (Get-FileHash -LiteralPath $assemblyPath -Algorithm SHA256).Hash
            if (-not [string]::Equals($diskHash, $match.Groups[4].Value,
                                     [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Worker loaded $label hash differs from its staged disk file: $assemblyPath"
            }
            $assemblies += [ordered]@{ label = $label; path = $assemblyPath;
                mvid = $match.Groups[3].Value; sha256 = $diskHash }
        }
        $stageIdentity = [ordered]@{ stageRoot = $stage; workerExe = (Join-Path $stage 'NativeWorker.exe');
            workerExeSha256 = (Get-FileHash -LiteralPath (Join-Path $stage 'NativeWorker.exe') -Algorithm SHA256).Hash;
            publishOutput = $output; releaseInfo = (Join-Path $stage 'release_info.json');
            stdout = (Join-Path $stage 'stdout.txt'); stderr = (Join-Path $stage 'stderr.txt');
            assemblies = $assemblies }
        [System.IO.File]::WriteAllText((Join-Path $stage 'stage_provenance.json'),
            ($stageIdentity | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
        if ($process.ExitCode -ne 0) { throw "Worker failed with exit $($process.ExitCode)." }
    } finally {
        # NativeWorker has no copied game instance directory. Clean up only
        # this invocation's process; retain its stage and audit evidence.
        if ($CleanupInstanceOnExit -and $null -ne $process) {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id
                $process.WaitForExit()
            }
            Write-Output "SLAY_NATIVE_WORKER_INSTANCE_CLEANED pid=$($process.Id)"
        }
        $env:STS2_GAME_PACK = $savedPack
        $env:STS2_WORKER_MODE = $savedMode
        $env:STS2_BENCHMARK_OUT = $savedOutput
        $env:STS2_MCTS_EXPORT_OUT = $savedExportOut
        $env:STS2_CROSS_ROOT_DIAG_OUT = $savedCrossRootOut
        $env:STS2_ENEMY_DAMAGE_DIAG_OUT = $savedEnemyDamageOut
        $env:STS2_MCTS_EXPORT_SEED = $savedExportSeed
        $env:STS2_MCTS_EXPORT_ENCOUNTER = $savedExportEncounter
        foreach ($name in $searchEnvironmentNames) {
            $value = $savedSearchEnvironment[$name]
            if ($null -eq $value) {
                Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
            } else {
                Set-Item -LiteralPath "Env:$name" -Value $value
            }
        }
    }
} finally { Pop-Location }
