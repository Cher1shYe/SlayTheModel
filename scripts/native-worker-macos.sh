#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
game_app="${STS2_GAME_APP:-$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app}"
mode="verify"
timeout_seconds="120"
skip_build="0"

usage() {
    cat <<'EOF'
Usage: ./scripts/native-worker-macos.sh [options]

  --game-app PATH
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
stage_dir="$repo_dir/artifacts/native-host"
worker_app="$stage_dir/NativeWorker.app"
worker_contents="$worker_app/Contents"
worker_exe="$worker_contents/MacOS/NativeWorker"
worker_data="$worker_contents/Resources/data_NativeWorker_macos_arm64"
build_output="$project_dir/.godot/mono/temp/bin/ExportRelease"

mkdir -p "$project_dir/.godot" "$stage_dir"
printf 'list=Array[Dictionary]([])\n' > "$project_dir/.godot/global_script_class_cache.cfg"

if [[ "$skip_build" == "0" ]]; then
    mkdir -p "$worker_contents/MacOS" "$worker_contents/Frameworks" "$worker_contents/Resources"
    dotnet build "$project_dir/Sts2.NativeWorker.csproj" \
        -c ExportRelease "-p:Sts2ManagedDir=$managed_dir"

    # Reuse the game's matching self-contained ARM64 runtime and dependency
    # manifest, then add the worker assembly. This avoids mixing MegaDot with a
    # stock Godot runtime and avoids downloading a second .NET runtime pack.
    mkdir -p "$worker_data"
    cp -R "$managed_dir/." "$worker_data/"
    cp "$build_output/NativeWorker.dll" "$worker_data/NativeWorker.dll"
    if [[ -f "$build_output/NativeWorker.pdb" ]]; then
        cp "$build_output/NativeWorker.pdb" "$worker_data/NativeWorker.pdb"
    fi
    cp "$managed_dir/sts2.deps.json" "$worker_data/NativeWorker.deps.json"
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
benchmark_out="$stage_dir/benchmark.json"
env -u SENTRY_GODOT_LIB_PATH \
    STS2_GAME_PACK="$game_pack" \
    STS2_WORKER_MODE="$mode" \
    STS2_BENCHMARK_OUT="$benchmark_out" \
    "$worker_exe" --headless --path "$project_dir" >"$stdout_log" 2>"$stderr_log" &
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
