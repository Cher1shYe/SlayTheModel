#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action="check"
game_app="${STS2_GAME_APP:-$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app}"
managed_dir="${Sts2ManagedDir:-}"
run_mode="play"
combat_policy="manual"
outside_combat_policy="manual"
export_dir=""
capture_history="0"

usage() {
    cat <<'EOF'
Usage: ./scripts/macos.sh [options]

  --action check|build|install|launch|probe|test
  --game-app PATH
  --managed-dir PATH
  --run-mode play|train
  --combat-policy manual|first-legal|mcts
  --outside-combat-policy manual|first-legal
  --export-dir PATH
  --capture-history
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
        --action) require_value "$@"; action="$2"; shift 2 ;;
        --game-app) require_value "$@"; game_app="$2"; shift 2 ;;
        --managed-dir) require_value "$@"; managed_dir="$2"; shift 2 ;;
        --run-mode) require_value "$@"; run_mode="$2"; shift 2 ;;
        --combat-policy) require_value "$@"; combat_policy="$2"; shift 2 ;;
        --outside-combat-policy) require_value "$@"; outside_combat_policy="$2"; shift 2 ;;
        --export-dir) require_value "$@"; export_dir="$2"; shift 2 ;;
        --capture-history) capture_history="1"; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$action" in check|build|install|launch|probe|test) ;; *) echo "Invalid --action: $action" >&2; exit 2 ;; esac
case "$run_mode" in play|train) ;; *) echo "Invalid --run-mode: $run_mode" >&2; exit 2 ;; esac
case "$combat_policy" in manual|first-legal|mcts) ;; *) echo "Invalid --combat-policy: $combat_policy" >&2; exit 2 ;; esac
case "$outside_combat_policy" in manual|first-legal) ;; *) echo "Invalid --outside-combat-policy: $outside_combat_policy" >&2; exit 2 ;; esac

cd "$repo_dir"

run_tests() {
    local project
    for project in SlayTheModel.Search.Smoke SlayTheModel.Protocol.Smoke SlayTheModel.Action.Smoke SlayTheModel.ReplaySearch.Smoke; do
        dotnet run --project "smoke/$project/$project.csproj" -c Release
    done
}

if [[ "$action" == "test" ]]; then
    dotnet --version
    run_tests
    exit 0
fi

game_exe="$game_app/Contents/MacOS/Slay the Spire 2"
game_resources="$game_app/Contents/Resources"
game_pack="$game_resources/Slay the Spire 2.pck"
if [[ -z "$managed_dir" ]]; then
    case "$(uname -m)" in
        arm64) managed_dir="$game_resources/data_sts2_macos_arm64" ;;
        x86_64) managed_dir="$game_resources/data_sts2_macos_x86_64" ;;
        *) echo "Unsupported macOS architecture: $(uname -m)" >&2; exit 1 ;;
    esac
fi

for path in "$game_exe" "$game_pack" "$managed_dir/sts2.dll" "$managed_dir/GodotSharp.dll" "$managed_dir/0Harmony.dll"; do
    if [[ ! -f "$path" ]]; then
        echo "Missing required game file: $path" >&2
        exit 1
    fi
done
dotnet --version
echo "Game: $game_app"
echo "Managed assemblies: $managed_dir"

if [[ "$action" == "check" ]]; then
    exit 0
fi

if [[ "$action" == "probe" ]]; then
    dotnet run --project tools/Sts2.AbiProbe -- \
        --assembly "$managed_dir/sts2.dll" \
        --contract contracts/sts2-v0.111.0.json \
        --out artifacts/abi/sts2-macos.json
    exit 0
fi

if [[ "$action" == "launch" ]]; then
    if pgrep -x "Slay the Spire 2" >/dev/null 2>&1; then
        echo "Exit the running game before launching." >&2
        exit 1
    fi
    if [[ -z "$export_dir" ]]; then export_dir="$repo_dir/artifacts/live-capture"; fi
    mkdir -p "$export_dir"
    worker_exe="$repo_dir/artifacts/native-host/NativeWorker.app/Contents/MacOS/NativeWorker"
    if [[ "$run_mode" == "play" && "$combat_policy" == "mcts" && ! -x "$worker_exe" ]]; then
        echo "Build and verify the macOS native worker with ./scripts/native-worker-macos.sh first." >&2
        exit 1
    fi
    env \
        SLAY_THE_MODEL_EXPORT_DIR="$export_dir" \
        SLAY_THE_MODEL_CAPTURE_HISTORY="$capture_history" \
        SLAY_THE_MODEL_RUN_MODE="$run_mode" \
        SLAY_THE_MODEL_COMBAT_POLICY="$combat_policy" \
        SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY="$outside_combat_policy" \
        SLAY_THE_MODEL_LIVE_POLICY= \
        SLAY_THE_MODEL_WORKER_EXE="$worker_exe" \
        SLAY_THE_MODEL_WORKER_PROJECT="$repo_dir/tools/Sts2.NativeWorker" \
        STS2_GAME_PACK="$game_pack" \
        SLAY_THE_MODEL_AUTOSLAY_SEED= \
        SteamAppId=2868840 \
        SteamGameId=2868840 \
        "$game_exe" &
    game_pid=$!
    echo "Started pid=$game_pid runMode=$run_mode combatPolicy=$combat_policy outsideCombatPolicy=$outside_combat_policy captures=$export_dir"
    exit 0
fi

if [[ "$action" == "install" ]] && pgrep -x "Slay the Spire 2" >/dev/null 2>&1; then
    echo "Exit the game before installing the mod." >&2
    exit 1
fi

dotnet build src/SlayTheModel.Sts2.ModAdapter/SlayTheModel.Sts2.ModAdapter.csproj \
    -c Release "-p:Sts2ManagedDir=$managed_dir"

if [[ "$action" == "install" ]]; then
    mod_dir="$game_app/Contents/MacOS/mods/SlayTheModelAdapter"
    mkdir -p "$mod_dir"
    cp src/SlayTheModel.Sts2.ModAdapter/bin/Release/net9.0/SlayTheModelAdapter.dll "$mod_dir/"
    cp src/SlayTheModel.Sts2.ModAdapter/SlayTheModelAdapter.json "$mod_dir/"
    echo "Installed: $mod_dir"
fi
