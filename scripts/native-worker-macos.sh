#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
game_app="${STS2_GAME_APP:-$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app}"
# RitsuLib is a build/runtime dependency of the imported Combat Solver backend.
# Allow non-default Steam libraries to override it without editing this script.
ritsu_root="${STS2_RITSULIB_DIR:-$HOME/Library/Application Support/Steam/steamapps/workshop/content/2868840/3747602295}"
mode="verify"
timeout_seconds="120"
skip_build="0"

usage() {
    cat <<'EOF'
Usage: ./scripts/native-worker-macos.sh [options]

  --game-app PATH
  --ritsu-lib-root PATH
  --mode verify|benchmark
  --timeout-seconds NUMBER
  --skip-build
EOF
}

require_value() {
    if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Missing value for $1" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --game-app) require_value "$@"; game_app="$2"; shift 2 ;;
        --ritsu-lib-root) require_value "$@"; ritsu_root="$2"; shift 2 ;;
        --mode) require_value "$@"; mode="$2"; shift 2 ;;
        --timeout-seconds) require_value "$@"; timeout_seconds="$2"; shift 2 ;;
        --skip-build) skip_build="1"; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$mode" in verify|benchmark) ;; *) echo "Invalid --mode: $mode" >&2; exit 2 ;; esac
if [[ ! "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
    echo "--timeout-seconds must be a positive integer." >&2
    exit 2
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    echo "The macOS native worker is currently pinned to the verified ARM64 game assembly." >&2
    exit 1
fi

cd "$repo_dir"
game_contents="$game_app/Contents"
game_resources="$game_contents/Resources"
game_exe="$game_contents/MacOS/Slay the Spire 2"
managed_dir="$game_resources/data_sts2_macos_arm64"
game_pack="$game_resources/Slay the Spire 2.pck"
contract="contracts/sts2-v0.111.0.json"
expected_hash="$(awk -F'"' '/"sha256"/ { print tolower($4); exit }' "$contract")"
actual_hash="$(shasum -a 256 "$managed_dir/sts2.dll" | awk '{ print $1 }')"
if [[ -z "$expected_hash" || "$actual_hash" != "$expected_hash" ]]; then
    echo "The native worker is pinned to the verified macOS ARM64 v0.111.0 assembly." >&2
    exit 1
fi

project_dir="$repo_dir/tools/Sts2.NativeWorker"
combat_solver_root="$repo_dir/combat"
stage_dir="$repo_dir/artifacts/native-host"
worker_app="$stage_dir/NativeWorker.app"
worker_contents="$worker_app/Contents"
worker_exe="$worker_contents/MacOS/NativeWorker"
worker_data="$worker_contents/Resources/data_NativeWorker_macos_arm64"
build_output="$project_dir/.godot/mono/temp/bin/ExportRelease"

# Validate third-party source and binary inputs before starting the expensive
# Godot build. This keeps path/setup mistakes separate from compiler failures.
if [[ ! -f "$combat_solver_root/CombatSolver.csproj" ]]; then
    echo "Combat Solver source is required at $combat_solver_root." >&2
    exit 1
fi
# Native replay correctness is tied to the imported solver revision. Accept
# either a nested development checkout or the provenance file shipped here.
source_commit_path="$combat_solver_root/.source-commit"
if [[ -d "$combat_solver_root/.git" ]]; then
    combat_solver_commit="$(git -C "$combat_solver_root" rev-parse HEAD)"
elif [[ -f "$source_commit_path" ]]; then
    combat_solver_commit="$(tr -d '[:space:]' < "$source_commit_path")"
else
    combat_solver_commit=""
fi
if [[ "$combat_solver_commit" != "8826a333a6d48e05f0e368ee2db5d4a15092382e" ]]; then
    echo "Combat Solver must be based on verified commit 8826a333; found $combat_solver_commit." >&2
    exit 1
fi
if [[ ! -f "$ritsu_root/compat/0.111.0/STS2-RitsuLib.dll" ]]; then
    echo "RitsuLib v0.111.0 was not found at $ritsu_root." >&2
    echo "Pass --ritsu-lib-root or set STS2_RITSULIB_DIR." >&2
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required to merge the game's self-contained deps with worker dependencies." >&2
    exit 1
fi

mkdir -p "$project_dir/.godot" "$stage_dir"
printf 'list=Array[Dictionary]([])\n' > "$project_dir/.godot/global_script_class_cache.cfg"

if [[ "$skip_build" == "0" ]]; then
    mkdir -p "$worker_contents/MacOS" "$worker_contents/Frameworks" "$worker_contents/Resources"
    dotnet build "$project_dir/Sts2.NativeWorker.csproj" \
        -c ExportRelease \
        "-p:Sts2ManagedDir=$managed_dir" \
        "-p:Sts2DataDir=$managed_dir" \
        "-p:CombatSolverRoot=$combat_solver_root" \
        "-p:RitsuLibRoot=$ritsu_root" \
        "-p:RitsuWorkshopRoot=$ritsu_root" \
        "-p:RitsuLibDir=$ritsu_root/compat/0.111.0" \
        -p:CopyModOnBuild=false

    # Reuse the game's matching self-contained ARM64 runtime and dependency
    # manifest, then add the worker assembly. This avoids mixing MegaDot with a
    # stock Godot runtime and avoids downloading a second .NET runtime pack.
    mkdir -p "$worker_data"
    cp -R "$managed_dir/." "$worker_data/"
    # ProjectReference keeps Search and CombatSolver as separate assemblies.
    # Copy every build-produced DLL except the game/Godot assemblies already
    # supplied by the matching game runtime copied above. This preserves ABI
    # compatibility while making the worker's dependency graph complete.
    for dependency in "$build_output"/*.dll; do
        case "$(basename "$dependency")" in
            sts2.dll|GodotSharp.dll|0Harmony.dll) continue ;;
        esac
        cp "$dependency" "$worker_data/"
    done
    if [[ -f "$build_output/NativeWorker.pdb" ]]; then
        cp "$build_output/NativeWorker.pdb" "$worker_data/NativeWorker.pdb"
    fi
    # MegaDot's executable is a self-contained custom Godot host. The game's
    # deps file carries its ARM64 CoreCLR/runtime-pack records, while the normal
    # worker deps file carries CombatSolver/Search/RitsuLib. Build one primary
    # deps file containing both sets; replacing either side outright breaks
    # host startup or managed project-reference resolution.
    deps_output="$worker_data/NativeWorker.deps.json"
    jq -s '
      .[0] as $game
      | .[1] as $worker
      | ($game.runtimeTarget.name) as $gameTarget
      | ($worker.runtimeTarget.name) as $workerTarget
      | ($worker.targets[$workerTarget]
          | with_entries(select(.key | test("^(NativeWorker|CombatSolver|SlayTheModel\\.Search|STS2-RitsuLib)")))) as $workerTargets
      | ($worker.libraries
          | with_entries(select(.key | test("^(NativeWorker|CombatSolver|SlayTheModel\\.Search|STS2-RitsuLib)")))) as $workerLibraries
      | $game
      | .targets[$gameTarget] += $workerTargets
      | .libraries += $workerLibraries
    ' "$managed_dir/sts2.deps.json" "$build_output/NativeWorker.deps.json" > "$deps_output.tmp"
    mv "$deps_output.tmp" "$deps_output"
    cp "$managed_dir/sts2.runtimeconfig.json" "$worker_data/NativeWorker.runtimeconfig.json"

    cp "$game_exe" "$worker_exe"
    chmod +x "$worker_exe"
    cp -R "$game_contents/Frameworks/." "$worker_contents/Frameworks/"
    cp "$game_contents/Info.plist" "$worker_contents/Info.plist"
    /usr/libexec/PlistBuddy -c 'Set :CFBundleExecutable NativeWorker' "$worker_contents/Info.plist"
    /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier dev.slaythemodel.NativeWorker' "$worker_contents/Info.plist"
    cp "$game_resources/release_info.json" "$worker_contents/Resources/release_info.json"
fi

if [[ ! -x "$worker_exe" || ! -f "$worker_data/NativeWorker.dll" ]]; then
    echo "Native worker build is incomplete: $worker_app" >&2
    exit 1
fi

stdout_log="$stage_dir/stdout.txt"
stderr_log="$stage_dir/stderr.txt"
godot_log="$stage_dir/godot-worker.log"
benchmark_out="$stage_dir/benchmark.json"
env -u SENTRY_GODOT_LIB_PATH \
    STS2_GAME_PACK="$game_pack" \
    STS2_WORKER_MODE="$mode" \
    STS2_BENCHMARK_OUT="$benchmark_out" \
    "$worker_exe" --headless --path "$project_dir" --log-file "$godot_log" >"$stdout_log" 2>"$stderr_log" &
worker_pid=$!
deadline=$((SECONDS + timeout_seconds))
timed_out="0"
while kill -0 "$worker_pid" 2>/dev/null; do
    if (( SECONDS >= deadline )); then
        timed_out="1"
        kill "$worker_pid" 2>/dev/null || true
        sleep 1
        kill -9 "$worker_pid" 2>/dev/null || true
        break
    fi
    sleep 1
done
if wait "$worker_pid"; then worker_status=0; else worker_status=$?; fi

tail -n 20 "$stdout_log" || true
tail -n 20 "$stderr_log" || true
if [[ "$timed_out" == "1" ]]; then
    echo "Worker exceeded $timeout_seconds seconds and was stopped. See $stage_dir logs." >&2
    exit 1
fi
if [[ "$worker_status" -ne 0 ]]; then
    echo "Worker failed with exit $worker_status. See $stage_dir logs." >&2
    exit "$worker_status"
fi
