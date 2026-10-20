#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action="check"
game_app="${STS2_GAME_APP:-$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app}"
managed_dir="${Sts2ManagedDir:-}"
dataset_dir="$repo_dir/artifacts/human-dataset"
information_mode="auto"
actor="human"

usage() {
    cat <<'EOF'
Usage: ./scripts/collector-macos.sh [options]

  --action check|build|install|launch|test
  --game-app PATH
  --managed-dir PATH
  --dataset-dir PATH
  --information-mode auto|no-sl|sl
  --actor human

The collector is read-only: it records local JSONL and never uploads or plays.
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
        --dataset-dir) require_value "$@"; dataset_dir="$2"; shift 2 ;;
        --information-mode) require_value "$@"; information_mode="$2"; shift 2 ;;
        --actor) require_value "$@"; actor="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$action" in check|build|install|launch|test) ;; *) echo "Invalid --action: $action" >&2; exit 2 ;; esac
case "$information_mode" in auto|no-sl|sl) ;; *) echo "Invalid --information-mode: $information_mode" >&2; exit 2 ;; esac
if [[ "$actor" != "human" ]]; then
    echo "--actor currently accepts only: human" >&2
    exit 2
fi
if [[ "$dataset_dir" =~ [[:cntrl:]] ]]; then
    echo "--dataset-dir cannot contain control characters" >&2
    exit 2
fi

cd "$repo_dir"

if [[ "$action" == "test" ]]; then
    dotnet --version
    dotnet build smoke/SlayTheModel.Collector.Smoke/SlayTheModel.Collector.Smoke.csproj \
        -c Release -m:1 -nodeReuse:false -p:UseSharedCompilation=false
    dotnet smoke/SlayTheModel.Collector.Smoke/bin/Release/net9.0/SlayTheModel.Collector.Smoke.dll
    exit 0
fi

game_exe="$game_app/Contents/MacOS/Slay the Spire 2"
game_resources="$game_app/Contents/Resources"
if [[ -z "$managed_dir" ]]; then
    case "$(uname -m)" in
        arm64) managed_dir="$game_resources/data_sts2_macos_arm64" ;;
        x86_64) managed_dir="$game_resources/data_sts2_macos_x86_64" ;;
        *) echo "Unsupported macOS architecture: $(uname -m)" >&2; exit 1 ;;
    esac
fi

for path in "$game_exe" "$managed_dir/sts2.dll" "$managed_dir/GodotSharp.dll" "$managed_dir/0Harmony.dll"; do
    if [[ ! -f "$path" ]]; then
        echo "Missing required game file: $path" >&2
        exit 1
    fi
done

if [[ "$dataset_dir" != /* ]]; then
    dataset_dir="$repo_dir/${dataset_dir#./}"
fi
if [[ "$action" == "install" || "$action" == "launch" ]]; then
    dataset_dir="$(mkdir -p "$dataset_dir" && cd "$dataset_dir" && pwd)"
fi
mod_dir="$game_app/Contents/MacOS/mods/SlayTheModelDataCollector"
config_path="$mod_dir/SlayTheModelDataCollector.runtime.json"

write_runtime_config() {
    mkdir -p "$mod_dir"
    local escaped_dataset escaped_actor
    escaped_dataset="${dataset_dir//\\/\\\\}"
    escaped_dataset="${escaped_dataset//\"/\\\"}"
    escaped_actor="${actor//\\/\\\\}"
    escaped_actor="${escaped_actor//\"/\\\"}"
    printf '%s\n' \
        '{' \
        '  "SLAY_THE_MODEL_COLLECTOR_ENABLED": "1",' \
        "  \"SLAY_THE_MODEL_DATASET_DIR\": \"$escaped_dataset\"," \
        "  \"SLAY_THE_MODEL_INFORMATION_MODE\": \"$information_mode\"," \
        "  \"SLAY_THE_MODEL_COLLECTOR_ACTOR\": \"$escaped_actor\"" \
        '}' > "$config_path"
    echo "Runtime config: $config_path"
}

dotnet --version
echo "Game: $game_app"
echo "Managed assemblies: $managed_dir"
echo "Dataset: $dataset_dir"

if [[ "$action" == "check" ]]; then
    exit 0
fi

if [[ "$action" == "launch" ]]; then
    if pgrep -x "Slay the Spire 2" >/dev/null 2>&1; then
        echo "Exit the running game before launching." >&2
        exit 1
    fi
    if [[ ! -f "$mod_dir/SlayTheModelDataCollector.dll" ]]; then
        echo "Collector is not installed. Run --action install first." >&2
        exit 1
    fi
    write_runtime_config
    env \
        SLAY_THE_MODEL_COLLECTOR_ENABLED=1 \
        SLAY_THE_MODEL_DATASET_DIR="$dataset_dir" \
        SLAY_THE_MODEL_INFORMATION_MODE="$information_mode" \
        SLAY_THE_MODEL_COLLECTOR_ACTOR="$actor" \
        SteamAppId=2868840 \
        SteamGameId=2868840 \
        "$game_exe" &
    echo "Started collector informationMode=$information_mode actor=$actor dataset=$dataset_dir"
    exit 0
fi

if [[ "$action" == "install" ]] && pgrep -x "Slay the Spire 2" >/dev/null 2>&1; then
    echo "Exit the game before installing the collector." >&2
    exit 1
fi

dotnet build src/SlayTheModel.Sts2.DataCollector/SlayTheModel.Sts2.DataCollector.csproj \
    -c Release "-p:Sts2ManagedDir=$managed_dir"

if [[ "$action" == "install" ]]; then
    mkdir -p "$mod_dir"
    cp src/SlayTheModel.Sts2.DataCollector/bin/Release/net9.0/SlayTheModelDataCollector.dll "$mod_dir/"
    cp src/SlayTheModel.Sts2.DataCollector/SlayTheModelDataCollector.json "$mod_dir/"
    write_runtime_config
    echo "Installed: $mod_dir"
fi
