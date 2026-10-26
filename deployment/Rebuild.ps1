$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Cmake = Join-Path $Root '.venv\Scripts\cmake.exe'
& $Cmake -S "$Root\simulator" -B "$Root\simulator\build312" -G 'Visual Studio 18 2026' -A x64 "-DPYTHON_EXECUTABLE=$Root/.venv/Scripts/python.exe" '-DCMAKE_POLICY_VERSION_MINIMUM=3.5'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Cmake --build "$Root\simulator\build312" --config Release --target slaythespire -j 4
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Cmake -S "$Root\sts-rl-agent\sim_patch\tests" -B "$PSScriptRoot\combat-tests" -G 'Visual Studio 18 2026' -A x64 "-DSTS_SIM_ROOT=$Root/simulator"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Cmake --build "$PSScriptRoot\combat-tests" --config Release -j 4
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$Root\.venv\Scripts\ctest.exe" --test-dir "$PSScriptRoot\combat-tests" -C Release --output-on-failure
exit $LASTEXITCODE
